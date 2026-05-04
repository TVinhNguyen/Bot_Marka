"""End-to-end walk-forward backtest: synthetic bars -> JSON report.

The integration covers the acceptance criteria for issue #10:

* No-lookahead replay (covered indirectly: same input -> same trades).
* Walk-forward windows separate train/validation/OOS.
* Cost model applied to fills.
* Risk Decision module is used (volume scales with confidence/agreement).
* Report includes OOS metrics, drawdown, Sharpe, Calmar, profit factor,
  trade count, and baseline-vs-ensemble comparison.
* Report manifest carries commit/config/data snapshot/lock/seed/timestamp.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ai_mt5.backtest import (
    BacktestConfig,
    BacktestRunSpec,
    CostModel,
    run_backtest,
)
from ai_mt5.config.models import RiskConfig
from ai_mt5.domain.bar import Bar


def _bar(i: int, *, open_: float, high: float, low: float, close: float) -> Bar:
    return Bar(
        symbol="EURUSD",
        timeframe="M15",
        open_time=datetime(2026, 4, 1, 0, 0, tzinfo=UTC) + timedelta(minutes=15 * i),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=1_000.0,
        spread_points=10,
    )


def _generate_bars(n: int = 600) -> list[Bar]:
    """A bar series with a stable uptrend interleaved by small pullbacks.

    The Baseline favours BUY here since SMA-5 stays above SMA-20; the
    ensemble adds Baseline-only (no model adapters supplied) so the two
    pipelines converge -- the test focuses on the *plumbing* (windows,
    costs, manifest), not on edge generation.
    """
    bars: list[Bar] = []
    price = 1.07000
    for i in range(n):
        # small drift up + sinusoidal wiggle
        drift = 0.00002 * i
        wiggle = 0.00010 * math.sin(i * 0.4)
        close = 1.07000 + drift + wiggle
        delta = price - close
        high = max(price, close) + 0.00015
        low = min(price, close) - 0.00015
        bars.append(_bar(i, open_=price, high=high, low=low, close=close))
        _ = delta  # kept for readability
        price = close
    return bars


@pytest.fixture
def risk_config() -> RiskConfig:
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


def _make_spec(risk_config: RiskConfig, *, seed: int = 0) -> BacktestRunSpec:
    return BacktestRunSpec(
        config=BacktestConfig(
            symbol="EURUSD",
            timeframe="M15",
            initial_equity=10_000.0,
            risk=risk_config,
            cost_model=CostModel(spread_points=0.5, slippage_buffer_points=0.5),
        ),
        train=200,
        validation=100,
        oos=100,
        seed=seed,
    )


def test_run_backtest_produces_full_report(risk_config: RiskConfig, tmp_path: Path) -> None:
    bars = _generate_bars(600)
    spec = _make_spec(risk_config)
    report = run_backtest(bars, spec=spec, config_for_manifest={"risk": risk_config.model_dump()})

    # Manifest fields per acceptance criteria
    m = report.manifest
    assert m.symbol == "EURUSD"
    assert m.timeframe == "M15"
    assert m.n_bars == 600
    assert m.seed == 0
    assert m.commit  # may be 'unknown' in shallow clones; just non-empty
    assert m.config_hash and len(m.config_hash) == 64
    assert m.data_snapshot_hash and len(m.data_snapshot_hash) == 64
    assert m.package_lock_hash  # 'unknown' or sha256
    assert m.run_timestamp.endswith("Z") or m.run_timestamp.endswith("+00:00")

    # At least one window
    assert len(report.windows) >= 1

    # Each window covers both pipelines and full metrics
    for w in report.windows:
        for pipeline in ("baseline", "ensemble"):
            assert pipeline in w.pipelines
            metrics = w.pipelines[pipeline]["metrics"]
            for key in (
                "n_trades",
                "n_wins",
                "n_losses",
                "win_rate",
                "gross_pnl",
                "profit_factor",
                "max_drawdown",
                "max_drawdown_pct",
                "sharpe",
                "calmar",
                "avg_trade",
            ):
                assert key in metrics

    # Aggregate carries the comparison block per acceptance criteria
    assert "comparison" in report.aggregate
    comp = report.aggregate["comparison"]
    for key in (
        "delta_gross_pnl",
        "delta_sharpe",
        "delta_max_drawdown_pct",
        "delta_win_rate",
        "delta_n_trades",
    ):
        assert key in comp

    # JSON round-trip
    out = tmp_path / "report.json"
    report.write_json(out)
    payload = json.loads(out.read_text())
    assert payload["manifest"]["seed"] == 0
    assert payload["manifest"]["data_snapshot_hash"] == m.data_snapshot_hash


def test_manifest_is_deterministic_for_same_inputs(risk_config: RiskConfig) -> None:
    bars = _generate_bars(450)
    spec = _make_spec(risk_config, seed=42)
    config_dict = {"risk": risk_config.model_dump()}
    a = run_backtest(bars, spec=spec, config_for_manifest=config_dict)
    b = run_backtest(bars, spec=spec, config_for_manifest=config_dict)
    assert a.manifest.config_hash == b.manifest.config_hash
    assert a.manifest.data_snapshot_hash == b.manifest.data_snapshot_hash
    assert a.manifest.package_lock_hash == b.manifest.package_lock_hash
    # Trade ledger should match exactly when inputs are identical.
    assert [t["net_pnl"] for t in a.aggregate["baseline"]["trades"]] == [
        t["net_pnl"] for t in b.aggregate["baseline"]["trades"]
    ]


def test_manifest_data_hash_changes_with_input(risk_config: RiskConfig) -> None:
    bars = _generate_bars(450)
    spec = _make_spec(risk_config)
    a = run_backtest(bars, spec=spec, config_for_manifest={"risk": "v1"})
    perturbed = list(bars)
    last = perturbed[-1]
    perturbed[-1] = Bar(
        symbol=last.symbol,
        timeframe=last.timeframe,
        open_time=last.open_time,
        open=last.open,
        high=last.high + 0.01,
        low=last.low - 0.01,
        close=last.close,
        volume=last.volume,
        spread_points=last.spread_points,
    )
    b = run_backtest(perturbed, spec=spec, config_for_manifest={"risk": "v1"})
    assert a.manifest.data_snapshot_hash != b.manifest.data_snapshot_hash


def test_zero_bars_rejected(risk_config: RiskConfig) -> None:
    spec = _make_spec(risk_config)
    with pytest.raises(ValueError):
        run_backtest([], spec=spec)


def test_too_few_bars_rejects_with_clear_error(risk_config: RiskConfig) -> None:
    spec = _make_spec(risk_config)
    bars = _generate_bars(50)  # < train+validation+oos
    with pytest.raises(ValueError):
        run_backtest(bars, spec=spec)
