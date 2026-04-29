"""Shared pytest fixtures."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_mt5.config.models import (
    AppConfig,
    EnvironmentConfig,
    ExecutionConfig,
    RiskConfig,
    StorageConfig,
    SymbolTimeframe,
)
from ai_mt5.domain.market import AccountSnapshot, MarketSnapshot
from ai_mt5.utils.logging_setup import configure_logging

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _reset_logging() -> None:
    configure_logging("DEBUG")


@pytest.fixture
def fixture_bars_path() -> Path:
    return REPO_ROOT / "data" / "fixtures" / "bars" / "EURUSD_M15.csv"


@pytest.fixture
def app_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        environment=EnvironmentConfig(mode="dry_run", timezone="UTC", log_level="INFO"),
        symbols=[
            SymbolTimeframe(symbol="EURUSD", timeframe="M15", enabled=True, spread_max_points=25)
        ],
        storage=StorageConfig(
            backend="jsonl",
            bars_path=str(tmp_path / "bars"),
            forecasts_path=str(tmp_path / "predictions"),
            audit_path=str(tmp_path / "audit"),
        ),
        risk=RiskConfig(
            base_risk_per_trade=0.002,
            max_risk_per_trade=0.005,
            min_risk_per_trade=0.0005,
            max_daily_loss=0.02,
            max_total_drawdown=0.08,
            max_positions_per_symbol=1,
            max_total_positions=3,
            max_trades_per_day=5,
            max_consecutive_losses=3,
            sl_atr_min=1.2,
            sl_atr_max=2.5,
            tp_atr=2.0,
            rr_min=1.0,
            margin_safety=0.8,
            spread_max_points={"EURUSD": 25},
            news_window_minutes={"high": [-30, 30], "medium": [-10, 15], "low": [0, 0]},
            kill_switch_file=str(tmp_path / "STOP"),
        ),
        execution=ExecutionConfig(
            dry_run=True,
            deviation_points=20,
            magic=26042901,
            order_comment="ai-mt5-mm",
            reconcile_on_start=True,
        ),
    )


@pytest.fixture
def account_snapshot() -> AccountSnapshot:
    return AccountSnapshot(
        balance=10_000.0,
        equity=10_000.0,
        free_margin=8_000.0,
        margin_used=2_000.0,
        open_positions=0,
        open_positions_for_symbol=0,
        consecutive_losses=0,
        trades_today=0,
        daily_pnl_pct=0.0,
        drawdown_pct=0.0,
        timestamp=datetime(2026, 4, 29, 13, 30, tzinfo=UTC),
    )


@pytest.fixture
def market_snapshot() -> MarketSnapshot:
    return MarketSnapshot(
        symbol="EURUSD",
        bid=1.07480,
        ask=1.07490,
        spread_points=10,
        point_size=0.00001,
        contract_size=100_000.0,
        volume_min=0.01,
        volume_max=50.0,
        volume_step=0.01,
        stop_level_points=10,
        atr=0.0010,
        margin_per_lot=1000.0,
        timestamp=datetime(2026, 4, 29, 13, 30, tzinfo=UTC),
    )
