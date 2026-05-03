"""Deterministic ensemble that turns Forecasts into a :class:`MetaSignal`.

Per issue #9:

* Forecast validation excludes invalid or NaN outputs.
* Weights rescale when optional models are unavailable.
* Agreement, raw score, cost penalty, uncertainty penalty,
  Event Risk penalty, final score, confidence, and veto reasons are
  recorded.
* Hard vetoes return HOLD for high Event Risk, excessive spread, low
  agreement, insufficient models, and adapter failure thresholds.
* Meta-Signal output includes the original component Forecasts for
  audit.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..domain.forecast import Direction, Forecast, MetaSignal
from ..text.event_risk import EventRiskOutput
from ..utils.time_utils import utcnow


@dataclass(frozen=True)
class EnsembleConfig:
    """Tunables for the ensemble.

    ``weights`` is a `name -> weight` mapping; any missing adapter causes
    a rescale of the remaining weights. ``min_models`` is the minimum
    number of non-HOLD forecasts required to trade (otherwise HOLD).
    ``event_risk_max`` is the soft ceiling; above it the ensemble vetoes.
    ``min_agreement`` is ``|sum(signed)| / sum(|signed|)`` for non-HOLD
    forecasts.
    """

    weights: dict[str, float] = field(
        default_factory=lambda: {
            "baseline_sma_momentum": 0.2,
            "timesfm": 0.3,
            "kronos": 0.25,
            "chronos": 0.25,
        }
    )
    min_models: int = 1
    event_risk_max: float = 0.6
    spread_max_points: int = 50
    min_agreement: float = 0.55
    max_adapter_failure_rate: float = 0.5
    cost_per_trade: float = 0.0002


def _is_valid(forecast: Forecast) -> bool:
    return (
        math.isfinite(forecast.score)
        and math.isfinite(forecast.raw_score)
        and math.isfinite(forecast.expected_return)
        and math.isfinite(forecast.uncertainty)
        and math.isfinite(forecast.confidence)
    )


class Ensemble:
    """Cost-aware, hard-veto ensemble. No sizing, no execution."""

    def __init__(self, config: EnsembleConfig | None = None) -> None:
        self._cfg = config or EnsembleConfig()

    def combine(
        self,
        forecasts: list[Forecast],
        *,
        event_risk: EventRiskOutput | None = None,
        spread_points: int = 0,
        n_adapter_failures: int = 0,
        n_adapter_total: int | None = None,
    ) -> MetaSignal:
        cfg = self._cfg
        veto: list[str] = []

        valid = [f for f in forecasts if _is_valid(f)]
        invalid = len(forecasts) - len(valid)

        # Rescale weights over the adapters that actually produced output.
        raw_weights = {f.model_name: cfg.weights.get(f.model_name, 0.0) for f in valid}
        total = sum(raw_weights.values())
        weights = {k: v / total for k, v in raw_weights.items()} if total > 0 else {}

        # Aggregate score over valid, non-HOLD forecasts.
        non_hold = [f for f in valid if f.direction != "HOLD"]
        weighted_score = sum(weights.get(f.model_name, 0.0) * f.score for f in valid)
        raw_score = sum(weights.get(f.model_name, 0.0) * f.raw_score for f in valid)
        agreement = self._agreement(non_hold)

        uncertainty_penalty = (
            sum(weights.get(f.model_name, 0.0) * f.uncertainty for f in valid) if weights else 1.0
        )
        event_penalty = event_risk.event_risk if event_risk is not None else 0.0
        cost_penalty = cfg.cost_per_trade

        final_score = (
            weighted_score
            - cost_penalty
            - 0.5 * uncertainty_penalty * abs(weighted_score)
            - 0.5 * event_penalty * abs(weighted_score)
        )

        # Confidence: mean of component confidences weighted, damped by
        # agreement and Event Risk.
        component_conf = (
            sum(weights.get(f.model_name, 0.0) * f.confidence for f in valid) if weights else 0.0
        )
        confidence = float(
            max(
                0.0,
                min(
                    1.0,
                    component_conf * agreement * (1.0 - event_penalty),
                ),
            )
        )

        # -- hard vetoes -----------------------------------------------------

        if len(non_hold) < cfg.min_models:
            veto.append("insufficient_models")
        if agreement < cfg.min_agreement and non_hold:
            veto.append("low_agreement")
        if spread_points > cfg.spread_max_points:
            veto.append("excessive_spread")
        if event_risk is not None:
            if event_risk.event_risk >= cfg.event_risk_max:
                veto.append("high_event_risk")
            if not event_risk.trade_permission:
                veto.append("event_risk_no_permission")
        failure_rate = 0.0
        denominator = n_adapter_total if n_adapter_total is not None else len(forecasts)
        if denominator:
            failure_rate = (n_adapter_failures + invalid) / denominator
        if failure_rate > cfg.max_adapter_failure_rate:
            veto.append("adapter_failure_rate")

        direction: Direction
        if veto or not non_hold:
            direction = "HOLD"
        elif final_score > 0:
            direction = "BUY"
        elif final_score < 0:
            direction = "SELL"
        else:
            direction = "HOLD"
            veto.append("zero_final_score")

        reason = (
            f"n_valid={len(valid)} n_non_hold={len(non_hold)} "
            f"agreement={agreement:.3f} final_score={final_score:+.4f} "
            f"event_risk={event_penalty:.3f} spread={spread_points}"
        )

        return MetaSignal(
            direction=direction,
            final_score=float(final_score),
            raw_score=float(raw_score),
            agreement=float(agreement),
            confidence=confidence,
            cost_penalty=float(cost_penalty),
            uncertainty_penalty=float(uncertainty_penalty),
            event_penalty=float(event_penalty),
            veto_reasons=veto,
            reason=reason,
            components={f.model_name: f for f in valid},
            timestamp=utcnow(),
        )

    # ---- helpers ---------------------------------------------------------

    def _agreement(self, non_hold: list[Forecast]) -> float:
        if not non_hold:
            return 0.0
        signed = [(1.0 if f.direction == "BUY" else -1.0) * abs(f.score) for f in non_hold]
        denom = sum(abs(s) for s in signed)
        if denom == 0:
            return 0.0
        return abs(sum(signed)) / denom
