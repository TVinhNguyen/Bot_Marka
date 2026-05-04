"""In-process metrics registry.

The runtime tick is single-threaded so a lock-free in-memory registry is
enough. Anything that wants metrics outside the process (Prometheus,
StatsD) can read :meth:`MetricsRegistry.snapshot` and ship it.

Metric kinds:

* ``counter`` -- monotonically non-decreasing integer (``forecasts_emitted``,
  ``risk_decisions{outcome=approved}``, ``errors{kind=adapter_failure}``).
* ``gauge``   -- last observed value (``open_positions``, ``equity``,
  ``drawdown_pct``, ``spread_points``).
* ``histogram`` -- streaming aggregate (count / sum / min / max / mean /
  stdev) for unbounded value streams like ``latency_ms``.

The registry never raises on duplicate registration -- it returns the
existing handle so the runtime can be safely re-entered (tests, replay).
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field
from typing import Any

LabelTuple = tuple[tuple[str, str], ...]


def _label_key(labels: dict[str, str] | None) -> LabelTuple:
    if not labels:
        return ()
    return tuple(sorted(labels.items()))


@dataclass(frozen=True)
class MetricSnapshot:
    """Immutable view of one labelled metric value at a point in time."""

    name: str
    kind: str
    labels: dict[str, str]
    value: float | dict[str, float]


@dataclass
class _CounterSeries:
    name: str
    description: str
    series: dict[LabelTuple, float] = field(default_factory=dict)

    def inc(self, labels: LabelTuple, by: float) -> None:
        if by < 0:
            raise ValueError(f"counter {self.name!r} cannot be decremented")
        self.series[labels] = self.series.get(labels, 0.0) + by


@dataclass
class _GaugeSeries:
    name: str
    description: str
    series: dict[LabelTuple, float] = field(default_factory=dict)

    def set(self, labels: LabelTuple, value: float) -> None:
        self.series[labels] = float(value)


@dataclass
class _HistogramAccumulator:
    n: int = 0
    sum: float = 0.0
    sum_sq: float = 0.0
    min: float = math.inf
    max: float = -math.inf

    def observe(self, value: float) -> None:
        self.n += 1
        self.sum += value
        self.sum_sq += value * value
        if value < self.min:
            self.min = value
        if value > self.max:
            self.max = value

    def to_dict(self) -> dict[str, float]:
        if self.n == 0:
            return {"count": 0, "sum": 0.0, "min": 0.0, "max": 0.0, "mean": 0.0, "stdev": 0.0}
        mean = self.sum / self.n
        # Population variance (no sample correction needed; we always hold full
        # observed series within the process).
        variance = max(self.sum_sq / self.n - mean * mean, 0.0)
        return {
            "count": float(self.n),
            "sum": self.sum,
            "min": self.min,
            "max": self.max,
            "mean": mean,
            "stdev": math.sqrt(variance),
        }


@dataclass
class _HistogramSeries:
    name: str
    description: str
    series: dict[LabelTuple, _HistogramAccumulator] = field(default_factory=dict)

    def observe(self, labels: LabelTuple, value: float) -> None:
        acc = self.series.setdefault(labels, _HistogramAccumulator())
        acc.observe(value)


class MetricsRegistry:
    """Process-local registry; thread-safe via a single lock."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, _CounterSeries] = {}
        self._gauges: dict[str, _GaugeSeries] = {}
        self._histograms: dict[str, _HistogramSeries] = {}

    # -- registration ------------------------------------------------------

    def counter(self, name: str, *, description: str = "") -> None:
        with self._lock:
            self._counters.setdefault(name, _CounterSeries(name=name, description=description))

    def gauge(self, name: str, *, description: str = "") -> None:
        with self._lock:
            self._gauges.setdefault(name, _GaugeSeries(name=name, description=description))

    def histogram(self, name: str, *, description: str = "") -> None:
        with self._lock:
            self._histograms.setdefault(name, _HistogramSeries(name=name, description=description))

    # -- recording ---------------------------------------------------------

    def inc(
        self,
        name: str,
        *,
        labels: dict[str, str] | None = None,
        by: float = 1.0,
    ) -> None:
        with self._lock:
            counter = self._counters.get(name)
            if counter is None:
                counter = _CounterSeries(name=name, description="")
                self._counters[name] = counter
            counter.inc(_label_key(labels), by)

    def set_gauge(
        self,
        name: str,
        value: float,
        *,
        labels: dict[str, str] | None = None,
    ) -> None:
        with self._lock:
            gauge = self._gauges.get(name)
            if gauge is None:
                gauge = _GaugeSeries(name=name, description="")
                self._gauges[name] = gauge
            gauge.set(_label_key(labels), value)

    def observe(
        self,
        name: str,
        value: float,
        *,
        labels: dict[str, str] | None = None,
    ) -> None:
        with self._lock:
            histogram = self._histograms.get(name)
            if histogram is None:
                histogram = _HistogramSeries(name=name, description="")
                self._histograms[name] = histogram
            histogram.observe(_label_key(labels), value)

    # -- snapshotting ------------------------------------------------------

    def snapshot(self) -> list[MetricSnapshot]:
        out: list[MetricSnapshot] = []
        with self._lock:
            for counter in self._counters.values():
                for labels_key, value in counter.series.items():
                    out.append(
                        MetricSnapshot(
                            name=counter.name,
                            kind="counter",
                            labels=dict(labels_key),
                            value=value,
                        )
                    )
            for gauge in self._gauges.values():
                for labels_key, value in gauge.series.items():
                    out.append(
                        MetricSnapshot(
                            name=gauge.name,
                            kind="gauge",
                            labels=dict(labels_key),
                            value=value,
                        )
                    )
            for histogram in self._histograms.values():
                for labels_key, acc in histogram.series.items():
                    out.append(
                        MetricSnapshot(
                            name=histogram.name,
                            kind="histogram",
                            labels=dict(labels_key),
                            value=acc.to_dict(),
                        )
                    )
        return out

    def to_dict(self) -> dict[str, list[dict[str, Any]]]:
        """Snapshot grouped by kind for human/JSON consumption."""
        snaps = self.snapshot()
        out: dict[str, list[dict[str, Any]]] = {"counter": [], "gauge": [], "histogram": []}
        for snap in snaps:
            out[snap.kind].append(
                {
                    "name": snap.name,
                    "labels": snap.labels,
                    "value": snap.value,
                }
            )
        return out


# -- canonical metric names ---------------------------------------------------

# Centralised so tick.py, agent layer, and tests share one source of truth.

FORECASTS_EMITTED = "forecasts_emitted"
META_SIGNALS_EMITTED = "meta_signals_emitted"
RISK_DECISIONS = "risk_decisions"  # labels: outcome=approved|rejected
ERRORS = "errors"  # labels: kind=...
SPREAD_POINTS = "spread_points"
LATENCY_MS = "tick_latency_ms"
OPEN_POSITIONS = "open_positions"
EQUITY = "equity"
DRAWDOWN_PCT = "drawdown_pct"
KILL_SWITCH_EVENTS = "kill_switch_events"  # labels: state=engaged|released
DATA_FRESHNESS_LAG_BARS = "data_freshness_lag_bars"


def register_default_metrics(registry: MetricsRegistry) -> None:
    """Pre-register the canonical metric names so snapshots include zeros."""
    registry.counter(FORECASTS_EMITTED, description="Number of Forecasts emitted by adapters.")
    registry.counter(META_SIGNALS_EMITTED, description="Number of Meta-Signals produced.")
    registry.counter(
        RISK_DECISIONS, description="Risk Decisions, labelled by outcome (approved|rejected)."
    )
    registry.counter(ERRORS, description="Pipeline errors, labelled by kind.")
    registry.counter(KILL_SWITCH_EVENTS, description="Kill switch state transitions.")
    registry.gauge(SPREAD_POINTS, description="Latest observed spread in points.")
    registry.gauge(OPEN_POSITIONS, description="Current open positions count (per symbol).")
    registry.gauge(EQUITY, description="Latest deposit-currency equity.")
    registry.gauge(DRAWDOWN_PCT, description="Latest drawdown as a fraction of peak equity.")
    registry.gauge(DATA_FRESHNESS_LAG_BARS, description="Bars behind real-time at the last tick.")
    registry.histogram(LATENCY_MS, description="Per-tick decision latency in milliseconds.")
