"""Issue #2: baseline adapter contract tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ai_mt5.baseline import BaselineAdapter
from ai_mt5.data import build_features
from ai_mt5.domain.bar import Bar
from ai_mt5.domain.forecast import Forecast


def _bars(closes: list[float]) -> list[Bar]:
    base = datetime(2026, 4, 29, 8, 0, tzinfo=UTC)
    return [
        Bar(
            symbol="EURUSD",
            timeframe="M15",
            open_time=base + timedelta(minutes=15 * i),
            open=c - 0.0001,
            high=c + 0.0003,
            low=c - 0.0003,
            close=c,
            volume=1000.0,
        )
        for i, c in enumerate(closes)
    ]


def _forecast_for(closes: list[float]) -> Forecast:
    bars = _bars(closes)
    feats = build_features(bars[:-1], bars[-1])
    return BaselineAdapter().forecast(feats, symbol="EURUSD", timeframe="M15")


def test_uptrend_forecasts_buy() -> None:
    closes = [1.07 + 0.0002 * i for i in range(25)]
    fc = _forecast_for(closes)
    assert fc.direction == "BUY"
    assert fc.score > 0
    assert fc.model_name == "baseline_sma_momentum"


def test_downtrend_forecasts_sell() -> None:
    closes = [1.10 - 0.0002 * i for i in range(25)]
    fc = _forecast_for(closes)
    assert fc.direction == "SELL"
    assert fc.score < 0


def test_flat_forecasts_hold() -> None:
    closes = [1.07] * 25
    fc = _forecast_for(closes)
    assert fc.direction == "HOLD"
    assert fc.score == 0.0


def test_forecast_contract_invariants() -> None:
    fc = _forecast_for([1.07 + 0.0002 * i for i in range(25)])
    assert 0.0 <= fc.confidence <= 1.0
    assert 0.0 <= fc.uncertainty <= 1.0
    assert fc.horizon > 0
    assert fc.timestamp.tzinfo is not None
