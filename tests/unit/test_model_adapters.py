"""Issue #7: offline Model Adapters share the Forecast contract."""

from __future__ import annotations

import math

import pytest

from ai_mt5.data.features import FeatureSet
from ai_mt5.domain.forecast import Forecast
from ai_mt5.models import ChronosAdapter, KronosAdapter, ModelAdapter, TimesFMAdapter
from ai_mt5.models.protocol import input_hash


@pytest.fixture
def bullish_features() -> FeatureSet:
    return FeatureSet(
        decision_time="2024-01-01T00:00:00+00:00",
        last_close=1.1050,
        return_1=0.0003,
        return_5=0.0020,
        sma_5=1.1040,
        sma_20=1.0990,
        momentum_5=0.0010,
        realized_vol_20=0.0006,
        n_bars_used=22,
    )


@pytest.fixture
def bearish_features() -> FeatureSet:
    return FeatureSet(
        decision_time="2024-01-01T00:00:00+00:00",
        last_close=1.0950,
        return_1=-0.0003,
        return_5=-0.0020,
        sma_5=1.0960,
        sma_20=1.1000,
        momentum_5=-0.0010,
        realized_vol_20=0.0006,
        n_bars_used=22,
    )


ADAPTERS = [TimesFMAdapter(), KronosAdapter(), ChronosAdapter()]


@pytest.mark.parametrize("adapter", ADAPTERS, ids=lambda a: a.name)
def test_adapter_conforms_to_protocol(adapter: ModelAdapter) -> None:
    assert isinstance(adapter, ModelAdapter)
    assert adapter.name
    assert adapter.version


@pytest.mark.parametrize("adapter", ADAPTERS, ids=lambda a: a.name)
def test_adapter_returns_valid_forecast(
    adapter: ModelAdapter, bullish_features: FeatureSet
) -> None:
    forecast = adapter.forecast(bullish_features, symbol="EURUSD", timeframe="M15")
    assert isinstance(forecast, Forecast)
    assert forecast.model_name == adapter.name
    assert forecast.metadata["model_version"] == adapter.version
    assert forecast.metadata["input_hash"] == input_hash(bullish_features)
    assert math.isfinite(forecast.score)
    assert 0.0 <= forecast.uncertainty <= 1.0
    assert 0.0 <= forecast.confidence <= 1.0


@pytest.mark.parametrize("adapter", ADAPTERS, ids=lambda a: a.name)
def test_adapter_is_deterministic(adapter: ModelAdapter, bullish_features: FeatureSet) -> None:
    a = adapter.forecast(bullish_features, symbol="EURUSD", timeframe="M15")
    b = adapter.forecast(bullish_features, symbol="EURUSD", timeframe="M15")
    assert a.direction == b.direction
    assert a.score == pytest.approx(b.score)
    assert a.raw_score == pytest.approx(b.raw_score)


@pytest.mark.parametrize("adapter", ADAPTERS, ids=lambda a: a.name)
def test_bullish_features_bias_buy_or_hold(
    adapter: ModelAdapter, bullish_features: FeatureSet
) -> None:
    forecast = adapter.forecast(bullish_features, symbol="EURUSD", timeframe="M15")
    assert forecast.direction in ("BUY", "HOLD")


@pytest.mark.parametrize("adapter", ADAPTERS, ids=lambda a: a.name)
def test_bearish_features_bias_sell_or_hold(
    adapter: ModelAdapter, bearish_features: FeatureSet
) -> None:
    forecast = adapter.forecast(bearish_features, symbol="EURUSD", timeframe="M15")
    assert forecast.direction in ("SELL", "HOLD")


def test_input_hash_is_stable_for_same_features(
    bullish_features: FeatureSet, bearish_features: FeatureSet
) -> None:
    assert input_hash(bullish_features) == input_hash(bullish_features)
    assert input_hash(bullish_features) != input_hash(bearish_features)
