"""Issue #3: ai-mt5 mt5-preflight CLI failure-mode regression tests.

The preflight command must never produce a raw Python traceback for
operator-facing errors. Every error path emits structured JSON so CI
pipelines and operator scripts can parse the result.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from click.testing import CliRunner

from ai_mt5.cli import cli


def _write_config(tmp_path: Path) -> Path:
    cfg_path = tmp_path / "config.yaml"
    cfg = {
        "environment": {"mode": "dry_run", "timezone": "UTC", "log_level": "INFO"},
        "symbols": [
            {"symbol": "EURUSD", "timeframe": "M15", "enabled": True, "spread_max_points": 25}
        ],
        "storage": {
            "backend": "jsonl",
            "bars_path": str(tmp_path / "bars"),
            "forecasts_path": str(tmp_path / "predictions"),
            "audit_path": str(tmp_path / "audit"),
        },
        "risk": {
            "base_risk_per_trade": 0.002,
            "max_risk_per_trade": 0.005,
            "min_risk_per_trade": 0.0005,
            "max_daily_loss": 0.02,
            "max_total_drawdown": 0.08,
            "max_positions_per_symbol": 1,
            "max_total_positions": 3,
            "max_trades_per_day": 5,
            "max_consecutive_losses": 3,
            "sl_atr_min": 1.2,
            "sl_atr_max": 2.5,
            "tp_atr": 2.0,
            "rr_min": 1.0,
            "margin_safety": 0.8,
            "spread_max_points": {"EURUSD": 25},
            "news_window_minutes": {"high": [-30, 30], "medium": [-10, 15], "low": [0, 0]},
            "kill_switch_file": str(tmp_path / "STOP"),
        },
        "execution": {
            "dry_run": True,
            "deviation_points": 20,
            "magic": 26042901,
            "order_comment": "ai-mt5",
            "reconcile_on_start": True,
        },
    }
    cfg_path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return cfg_path


def test_mt5_preflight_emits_structured_json_when_bridge_host_missing(
    tmp_path: Path, monkeypatch
) -> None:
    """Regression: MT5BridgeConfig.from_env() raises MT5ConnectionError
    when MT5_BRIDGE_HOST is not set. That call must be inside the same
    try/except as client.connect(), or the operator gets a raw Python
    traceback that breaks CI parsers."""
    cfg_path = _write_config(tmp_path)
    # Make absolutely sure the bridge host is not in the env. Other
    # MT5_* vars are harmless without the host.
    monkeypatch.delenv("MT5_BRIDGE_HOST", raising=False)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["mt5-preflight", "--config", str(cfg_path)],
        catch_exceptions=False,
    )
    assert result.exit_code == 1
    payload_lines = [ln for ln in result.output.splitlines() if ln.startswith("{")]
    assert payload_lines, f"expected JSON payload, got: {result.output!r}"
    payload = json.loads(payload_lines[-1])
    assert payload["ok"] is False
    assert any("bridge_error" in f for f in payload["failures"])
