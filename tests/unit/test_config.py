"""Issue #1: config validation fails fast for missing required sections."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from ai_mt5.config import ConfigError, load_config


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(dedent(body), encoding="utf-8")
    return path


def test_load_config_succeeds_for_dry_run_skeleton(tmp_path: Path) -> None:
    cfg = load_config(
        _write(
            tmp_path,
            """
            environment:
              mode: dry_run
              timezone: UTC
              log_level: INFO
            symbols:
              - symbol: EURUSD
                timeframe: M15
                enabled: true
                spread_max_points: 25
            storage:
              backend: jsonl
              bars_path: data/bars
              forecasts_path: data/predictions
              audit_path: audit
            risk:
              base_risk_per_trade: 0.002
              max_risk_per_trade: 0.005
              min_risk_per_trade: 0.0005
              max_daily_loss: 0.02
              max_total_drawdown: 0.08
              max_positions_per_symbol: 1
              max_total_positions: 3
              max_trades_per_day: 5
              max_consecutive_losses: 3
              sl_atr_min: 1.2
              sl_atr_max: 2.5
              tp_atr: 2.0
              rr_min: 1.0
              margin_safety: 0.8
            execution:
              dry_run: true
              deviation_points: 20
              magic: 26042901
              order_comment: "ai-mt5-mm"
            """,
        )
    )
    assert cfg.environment.mode == "dry_run"
    assert cfg.primary_symbol().symbol == "EURUSD"


@pytest.mark.parametrize(
    "missing_section",
    ["environment", "symbols", "storage", "risk", "execution"],
)
def test_missing_required_section_fails_fast(tmp_path: Path, missing_section: str) -> None:
    sections = {
        "environment": "environment:\n  mode: dry_run\n  timezone: UTC\n  log_level: INFO",
        "symbols": "symbols:\n  - {symbol: EURUSD, timeframe: M15, enabled: true}",
        "storage": "storage:\n  backend: jsonl\n  bars_path: data/bars\n  forecasts_path: data/predictions\n  audit_path: audit",
        "risk": (
            "risk:\n  base_risk_per_trade: 0.002\n  max_risk_per_trade: 0.005\n"
            "  min_risk_per_trade: 0.0005\n  max_daily_loss: 0.02\n  max_total_drawdown: 0.08\n"
            "  max_positions_per_symbol: 1\n  max_total_positions: 3\n  max_trades_per_day: 5\n"
            "  max_consecutive_losses: 3\n  sl_atr_min: 1.2\n  sl_atr_max: 2.5\n  tp_atr: 2.0\n"
            "  rr_min: 1.0\n  margin_safety: 0.8"
        ),
        "execution": (
            "execution:\n  dry_run: true\n  deviation_points: 20\n  magic: 26042901\n"
            '  order_comment: "ai-mt5-mm"\n  reconcile_on_start: true'
        ),
    }
    body = "\n".join(v for k, v in sections.items() if k != missing_section)
    path = tmp_path / "config.yaml"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(ConfigError) as excinfo:
        load_config(path)
    assert missing_section in str(excinfo.value)


def test_invalid_mode_fails_validation(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        environment:
          mode: TURBO
          timezone: UTC
        symbols:
          - {symbol: EURUSD, timeframe: M15, enabled: true}
        storage: {backend: jsonl, bars_path: x, forecasts_path: y, audit_path: z}
        risk:
          base_risk_per_trade: 0.002
          max_risk_per_trade: 0.005
          min_risk_per_trade: 0.0005
          max_daily_loss: 0.02
          max_total_drawdown: 0.08
          max_positions_per_symbol: 1
          max_total_positions: 3
          max_trades_per_day: 5
          max_consecutive_losses: 3
          sl_atr_min: 1.2
          sl_atr_max: 2.5
          tp_atr: 2.0
          rr_min: 1.0
          margin_safety: 0.8
        execution:
          dry_run: true
          deviation_points: 20
          magic: 26042901
          order_comment: "ai-mt5-mm"
        """,
    )
    with pytest.raises(ConfigError):
        load_config(path)


def test_no_enabled_symbols_fails(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        environment: {mode: dry_run, timezone: UTC}
        symbols:
          - {symbol: EURUSD, timeframe: M15, enabled: false}
        storage: {backend: jsonl, bars_path: x, forecasts_path: y, audit_path: z}
        risk:
          base_risk_per_trade: 0.002
          max_risk_per_trade: 0.005
          min_risk_per_trade: 0.0005
          max_daily_loss: 0.02
          max_total_drawdown: 0.08
          max_positions_per_symbol: 1
          max_total_positions: 3
          max_trades_per_day: 5
          max_consecutive_losses: 3
          sl_atr_min: 1.2
          sl_atr_max: 2.5
          tp_atr: 2.0
          rr_min: 1.0
          margin_safety: 0.8
        execution:
          dry_run: true
          deviation_points: 20
          magic: 26042901
          order_comment: "ai-mt5-mm"
        """,
    )
    with pytest.raises(ConfigError):
        load_config(path)


def test_dry_run_mode_requires_execution_dry_run_true(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        environment: {mode: dry_run, timezone: UTC}
        symbols:
          - {symbol: EURUSD, timeframe: M15, enabled: true}
        storage: {backend: jsonl, bars_path: x, forecasts_path: y, audit_path: z}
        risk:
          base_risk_per_trade: 0.002
          max_risk_per_trade: 0.005
          min_risk_per_trade: 0.0005
          max_daily_loss: 0.02
          max_total_drawdown: 0.08
          max_positions_per_symbol: 1
          max_total_positions: 3
          max_trades_per_day: 5
          max_consecutive_losses: 3
          sl_atr_min: 1.2
          sl_atr_max: 2.5
          tp_atr: 2.0
          rr_min: 1.0
          margin_safety: 0.8
        execution:
          dry_run: false
          deviation_points: 20
          magic: 26042901
          order_comment: "ai-mt5-mm"
        """,
    )
    with pytest.raises(ConfigError):
        load_config(path)


def test_env_substitution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _write(
        tmp_path,
        """
        environment:
          mode: ${ENV:dry_run}
          timezone: UTC
        symbols:
          - {symbol: EURUSD, timeframe: M15, enabled: true}
        storage: {backend: jsonl, bars_path: x, forecasts_path: y, audit_path: z}
        risk:
          base_risk_per_trade: 0.002
          max_risk_per_trade: 0.005
          min_risk_per_trade: 0.0005
          max_daily_loss: 0.02
          max_total_drawdown: 0.08
          max_positions_per_symbol: 1
          max_total_positions: 3
          max_trades_per_day: 5
          max_consecutive_losses: 3
          sl_atr_min: 1.2
          sl_atr_max: 2.5
          tp_atr: 2.0
          rr_min: 1.0
          margin_safety: 0.8
        execution:
          dry_run: true
          deviation_points: 20
          magic: 26042901
          order_comment: "ai-mt5-mm"
        """,
    )
    cfg = load_config(path, env={})
    assert cfg.environment.mode == "dry_run"  # default kicks in
