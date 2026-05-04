"""Offline evaluation for Model Adapters.

Takes a :class:`ModelAdapter`, a list of Closed Bars, and returns a
:class:`EvaluationReport` with directional accuracy, edge-after-cost,
and calibration / uncertainty diagnostics. The evaluator never looks
ahead: each decision uses only bars strictly before the realized bar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import fmean

from ..data.features import build_features
from ..domain.bar import Bar
from ..domain.forecast import Forecast
from .protocol import AdapterError, ModelAdapter


@dataclass(frozen=True)
class EvaluationReport:
    """Summary of running ``adapter`` over a sequence of Closed Bars."""

    adapter_name: str
    adapter_version: str
    n_decisions: int
    n_errors: int
    direction_accuracy: float
    edge_after_cost: float
    mean_uncertainty: float
    mean_confidence: float
    limitations: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True iff at least one decision succeeded."""
        return self.n_decisions > 0


def _decision_return(next_bar: Bar, prev_close: float, forecast: Forecast) -> float:
    raw = (next_bar.close - prev_close) / prev_close if prev_close else 0.0
    if forecast.direction == "BUY":
        return raw
    if forecast.direction == "SELL":
        return -raw
    return 0.0


def _hit(next_bar: Bar, prev_close: float, forecast: Forecast) -> int | None:
    if forecast.direction == "HOLD":
        return None
    move = next_bar.close - prev_close
    if forecast.direction == "BUY":
        return int(move > 0)
    return int(move < 0)


def evaluate_adapter(
    adapter: ModelAdapter,
    bars: list[Bar],
    *,
    cost_per_trade: float = 0.0,
    min_history: int = 21,
) -> EvaluationReport:
    """Walk ``bars`` forward, run the adapter at each step, score predictions.

    ``min_history`` controls how many warm-up bars the adapter sees before
    its first forecast. The default (21) lines up with the Baseline's
    SMA-20 window so the first Forecast is not dominated by padding.
    """
    if len(bars) < min_history + 1:
        return EvaluationReport(
            adapter_name=adapter.name,
            adapter_version=adapter.version,
            n_decisions=0,
            n_errors=0,
            direction_accuracy=0.0,
            edge_after_cost=0.0,
            mean_uncertainty=0.0,
            mean_confidence=0.0,
            limitations=["insufficient_history"],
        )

    returns: list[float] = []
    hits: list[int] = []
    uncertainties: list[float] = []
    confidences: list[float] = []
    errors = 0

    for i in range(min_history, len(bars) - 1):
        history = bars[: i + 1]
        decision_bar = bars[i + 1]
        features = build_features(history[:-1], decision_bar=history[-1])
        try:
            forecast = adapter.forecast(
                features, symbol=history[-1].symbol, timeframe=history[-1].timeframe
            )
        except AdapterError:
            errors += 1
            continue
        realized = _decision_return(decision_bar, history[-1].close, forecast)
        if forecast.direction != "HOLD":
            returns.append(realized - cost_per_trade)
            hit = _hit(decision_bar, history[-1].close, forecast)
            if hit is not None:
                hits.append(hit)
        uncertainties.append(forecast.uncertainty)
        confidences.append(forecast.confidence)

    n_decisions = len(uncertainties)
    limitations: list[str] = []
    if n_decisions == 0:
        limitations.append("no_decisions")
    if not hits:
        limitations.append("all_holds")

    return EvaluationReport(
        adapter_name=adapter.name,
        adapter_version=adapter.version,
        n_decisions=n_decisions,
        n_errors=errors,
        direction_accuracy=fmean(hits) if hits else 0.0,
        edge_after_cost=fmean(returns) if returns else 0.0,
        mean_uncertainty=fmean(uncertainties) if uncertainties else 0.0,
        mean_confidence=fmean(confidences) if confidences else 0.0,
        limitations=limitations,
    )
