"""Metrics registry primitives."""

from __future__ import annotations

import math

import pytest

from ai_mt5.observability.metrics import (
    DRAWDOWN_PCT,
    EQUITY,
    LATENCY_MS,
    MetricsRegistry,
    register_default_metrics,
)


def test_counter_increments_and_groups_by_label() -> None:
    reg = MetricsRegistry()
    reg.counter("forecasts_emitted")
    reg.inc("forecasts_emitted")
    reg.inc("forecasts_emitted")
    reg.inc("risk_decisions", labels={"outcome": "approved"})
    reg.inc("risk_decisions", labels={"outcome": "rejected"})
    reg.inc("risk_decisions", labels={"outcome": "rejected"})
    snap = {(s.name, tuple(sorted(s.labels.items()))): s for s in reg.snapshot()}
    assert snap[("forecasts_emitted", ())].value == 2
    assert snap[("risk_decisions", (("outcome", "approved"),))].value == 1
    assert snap[("risk_decisions", (("outcome", "rejected"),))].value == 2


def test_counter_rejects_negative_increment() -> None:
    reg = MetricsRegistry()
    with pytest.raises(ValueError):
        reg.inc("foo", by=-1.0)


def test_gauge_holds_last_value() -> None:
    reg = MetricsRegistry()
    reg.gauge(EQUITY)
    reg.set_gauge(EQUITY, 10_000.0)
    reg.set_gauge(EQUITY, 9_950.0)
    snaps = [s for s in reg.snapshot() if s.name == EQUITY]
    assert len(snaps) == 1
    assert snaps[0].value == 9_950.0


def test_histogram_aggregates_correctly() -> None:
    reg = MetricsRegistry()
    reg.histogram(LATENCY_MS)
    for v in [10.0, 20.0, 30.0]:
        reg.observe(LATENCY_MS, v)
    snaps = [s for s in reg.snapshot() if s.name == LATENCY_MS]
    assert len(snaps) == 1
    raw = snaps[0].value
    assert isinstance(raw, dict)
    assert raw["count"] == 3
    assert raw["sum"] == pytest.approx(60.0)
    assert raw["min"] == 10.0
    assert raw["max"] == 30.0
    assert raw["mean"] == pytest.approx(20.0)
    # variance = 200/3, stdev = sqrt(200/3) ≈ 8.165
    assert raw["stdev"] == pytest.approx(math.sqrt(200.0 / 3.0))


def test_histogram_empty_summary() -> None:
    reg = MetricsRegistry()
    reg.histogram("noop")
    snaps = reg.snapshot()
    # Empty histograms aren't emitted (no series yet).
    assert all(s.name != "noop" for s in snaps)


def test_to_dict_groups_by_kind() -> None:
    reg = MetricsRegistry()
    register_default_metrics(reg)
    reg.inc("forecasts_emitted")
    reg.set_gauge(DRAWDOWN_PCT, 0.03)
    reg.observe(LATENCY_MS, 12.5)
    out = reg.to_dict()
    counter_names = {entry["name"] for entry in out["counter"]}
    gauge_names = {entry["name"] for entry in out["gauge"]}
    histogram_names = {entry["name"] for entry in out["histogram"]}
    assert "forecasts_emitted" in counter_names
    assert DRAWDOWN_PCT in gauge_names
    assert LATENCY_MS in histogram_names


def test_register_default_metrics_is_idempotent() -> None:
    reg = MetricsRegistry()
    register_default_metrics(reg)
    register_default_metrics(reg)  # second call must not raise
    reg.inc("forecasts_emitted")
    assert any(s.name == "forecasts_emitted" for s in reg.snapshot())
