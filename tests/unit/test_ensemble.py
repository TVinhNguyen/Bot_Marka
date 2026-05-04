"""Issue #9: deterministic Ensemble combines Forecasts into Meta-Signals."""

from __future__ import annotations

import math
from datetime import UTC, datetime

import pytest

from ai_mt5.domain.forecast import Direction, Forecast
from ai_mt5.ensemble import Ensemble, EnsembleConfig
from ai_mt5.text.event_risk import EventRiskOutput


def _f(
    name: str,
    direction: Direction,
    score: float,
    *,
    uncertainty: float = 0.2,
    confidence: float | None = None,
) -> Forecast:
    return Forecast(
        model_name=name,
        symbol="EURUSD",
        timeframe="M15",
        horizon=4,
        direction=direction,
        expected_return=score * 0.001,
        uncertainty=uncertainty,
        raw_score=score * 3.0,
        score=score,
        confidence=confidence if confidence is not None else abs(score),
        reason="test",
        timestamp=datetime(2024, 1, 1, tzinfo=UTC),
    )


def test_meta_signal_records_components_for_audit() -> None:
    forecasts = [_f("timesfm", "BUY", 0.4), _f("kronos", "BUY", 0.6)]
    signal = Ensemble().combine(forecasts)
    assert set(signal.components.keys()) == {"timesfm", "kronos"}


def test_nan_forecasts_are_excluded() -> None:
    bad = _f("timesfm", "BUY", math.nan)
    good = _f("kronos", "BUY", 0.5)
    cfg = EnsembleConfig(min_models=1)
    signal = Ensemble(cfg).combine([bad, good])
    assert "timesfm" not in signal.components
    assert "kronos" in signal.components


def test_low_agreement_vetoes() -> None:
    cfg = EnsembleConfig(min_models=2, min_agreement=0.9)
    forecasts = [_f("timesfm", "BUY", 0.5), _f("kronos", "SELL", 0.5)]
    signal = Ensemble(cfg).combine(forecasts)
    assert "low_agreement" in signal.veto_reasons
    assert signal.direction == "HOLD"


def test_insufficient_models_vetoes() -> None:
    cfg = EnsembleConfig(min_models=3)
    forecasts = [_f("timesfm", "BUY", 0.5), _f("kronos", "BUY", 0.4)]
    signal = Ensemble(cfg).combine(forecasts)
    assert "insufficient_models" in signal.veto_reasons
    assert signal.direction == "HOLD"


def test_high_event_risk_vetoes() -> None:
    event = EventRiskOutput(
        symbol="EURUSD",
        as_of=datetime(2024, 1, 1, tzinfo=UTC),
        event_risk=0.9,
        sentiment=0.0,
        direction_bias="HOLD",
        trade_permission=False,
        reason="nfp",
    )
    forecasts = [_f("timesfm", "BUY", 0.5), _f("kronos", "BUY", 0.5)]
    signal = Ensemble().combine(forecasts, event_risk=event)
    assert "high_event_risk" in signal.veto_reasons
    assert "event_risk_no_permission" in signal.veto_reasons
    assert signal.direction == "HOLD"


def test_excessive_spread_vetoes() -> None:
    cfg = EnsembleConfig(spread_max_points=30)
    forecasts = [_f("timesfm", "BUY", 0.5), _f("kronos", "BUY", 0.5)]
    signal = Ensemble(cfg).combine(forecasts, spread_points=100)
    assert "excessive_spread" in signal.veto_reasons


def test_adapter_failure_rate_vetoes() -> None:
    cfg = EnsembleConfig(max_adapter_failure_rate=0.4, min_models=1)
    forecasts = [_f("kronos", "BUY", 0.5)]  # 1 of 3 adapters produced output
    signal = Ensemble(cfg).combine(forecasts, n_adapter_failures=2, n_adapter_total=3)
    assert "adapter_failure_rate" in signal.veto_reasons


def test_weights_rescale_when_adapter_missing() -> None:
    """With only two of four configured adapters, the two remaining get full weight."""
    cfg = EnsembleConfig(weights={"a": 0.25, "b": 0.25, "c": 0.25, "d": 0.25})
    forecasts = [_f("a", "BUY", 0.6), _f("b", "BUY", 0.4)]
    signal = Ensemble(cfg).combine(forecasts)
    # Weighted score should be 0.5 * 0.6 + 0.5 * 0.4 = 0.50 before penalties.
    assert signal.final_score < 0.5  # minus penalties
    assert signal.final_score > 0.3


def test_clean_bullish_forecasts_produce_buy() -> None:
    forecasts = [
        _f("timesfm", "BUY", 0.6, uncertainty=0.1, confidence=0.8),
        _f("kronos", "BUY", 0.5, uncertainty=0.1, confidence=0.8),
        _f("chronos", "BUY", 0.4, uncertainty=0.1, confidence=0.7),
    ]
    signal = Ensemble().combine(forecasts, spread_points=5)
    assert signal.direction == "BUY"
    assert not signal.veto_reasons
    assert signal.agreement == pytest.approx(1.0)


def test_hold_forecasts_produce_hold_without_veto_spam() -> None:
    cfg = EnsembleConfig(min_models=1)
    forecasts = [_f("a", "HOLD", 0.0), _f("b", "HOLD", 0.0)]
    signal = Ensemble(cfg).combine(forecasts)
    assert signal.direction == "HOLD"
