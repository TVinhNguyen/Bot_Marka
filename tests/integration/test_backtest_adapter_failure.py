"""WalkForwardEngine must propagate adapter failures so the ensemble can veto.

Mirrors the live tick parity: when a Model Adapter raises ``AdapterError``
the count is forwarded to ``Ensemble.combine(n_adapter_failures=...)`` so
the adapter_failure_rate hard veto can fire (see issue #9 + ADR 0006).
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

from ai_mt5.backtest import (
    BacktestConfig,
    CostModel,
    WalkForwardEngine,
    walk_forward_windows,
)
from ai_mt5.config.models import RiskConfig
from ai_mt5.data.features import FeatureSet
from ai_mt5.domain.bar import Bar
from ai_mt5.domain.forecast import Forecast
from ai_mt5.ensemble.ensemble import EnsembleConfig
from ai_mt5.models.protocol import AdapterError


def _bar(i: int, *, close: float) -> Bar:
    return Bar(
        symbol="EURUSD",
        timeframe="M15",
        open_time=datetime(2026, 4, 1, tzinfo=UTC) + timedelta(minutes=15 * i),
        open=close - 0.00005,
        high=close + 0.00020,
        low=close - 0.00020,
        close=close,
        volume=1_000.0,
        spread_points=10,
    )


def _bars(n: int = 250) -> list[Bar]:
    return [_bar(i, close=1.07 + 0.00002 * i + 0.0001 * math.sin(i * 0.4)) for i in range(n)]


def _risk_config() -> RiskConfig:
    return RiskConfig(
        base_risk_per_trade=0.005,
        max_risk_per_trade=0.01,
        min_risk_per_trade=0.001,
        max_daily_loss=0.05,
        max_total_drawdown=0.2,
        max_positions_per_symbol=1,
        max_total_positions=5,
        max_trades_per_day=20,
        max_consecutive_losses=5,
        sl_atr_min=1.0,
        sl_atr_max=2.5,
        tp_atr=2.0,
        rr_min=1.0,
        margin_safety=0.5,
    )


class _AlwaysFailingAdapter:
    """A Model Adapter that always raises ``AdapterError`` (failure mock)."""

    name = "always_failing"
    version = "0.0.0"

    def forecast(self, features: FeatureSet, *, symbol: str, timeframe: str) -> Forecast:
        raise AdapterError("forced failure")


def test_adapter_failures_are_forwarded_to_ensemble() -> None:
    """When 2 of 3 adapters fail (>50%), the ensemble must veto.

    Without the failure-count plumbing the engine would silently pass
    ``n_adapter_failures=0`` and the veto would never trigger -- matching
    the bug surfaced by Devin Review on PR #16.
    """
    bars = _bars(250)
    cfg = BacktestConfig(
        symbol="EURUSD",
        timeframe="M15",
        initial_equity=10_000.0,
        risk=_risk_config(),
        cost_model=CostModel(spread_points=0.5, slippage_buffer_points=0.5),
        # min_models=1 ensures the lone Baseline forecast is otherwise eligible.
        ensemble_config=EnsembleConfig(min_models=1, max_adapter_failure_rate=0.5),
    )
    engine = WalkForwardEngine(
        cfg,
        adapters=[_AlwaysFailingAdapter(), _AlwaysFailingAdapter()],
    )
    window = next(walk_forward_windows(len(bars), train=100, validation=50, oos=100))
    states = engine.run_window(bars, window)
    # Failure rate = 2/3 > 0.5 -> ensemble HOLDs every tick. Baseline
    # pipeline is unaffected (it does not see the failure count) and may
    # still trade.
    assert states["ensemble"].trades == []
    assert states["ensemble"].veto_count > 0
