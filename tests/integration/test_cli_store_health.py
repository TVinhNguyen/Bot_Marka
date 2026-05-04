"""Issue #6: ai-mt5 store-health CLI emits a JSON snapshot of the BarStore."""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

from ai_mt5.data import BarStore
from ai_mt5.domain.bar import Bar


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


def _seed_bars(tmp_path: Path) -> None:
    store = BarStore(tmp_path / "bars")
    base = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
    bars = [
        Bar(
            symbol="EURUSD",
            timeframe="M15",
            open_time=base + timedelta(minutes=15 * i),
            open=1.10,
            high=1.101,
            low=1.099,
            close=1.1005,
            volume=100.0,
            spread_points=5,
        )
        for i in range(3)
    ]
    store.append_many(bars)


def test_store_health_cli_emits_json_for_empty_store(tmp_path: Path) -> None:
    cfg_path = _write_config(tmp_path)
    cmd = f"{shlex.quote(sys.executable)} -m ai_mt5 store-health --config {shlex.quote(str(cfg_path))}"
    out = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=True)
    payload = json.loads(out.stdout.strip().splitlines()[-1])
    assert payload["symbol"] == "EURUSD"
    assert payload["timeframe"] == "M15"
    assert payload["bar_count"] == 0
    assert payload["freshness"]["state"] == "empty"
    assert payload["ok"] is False


def test_store_health_cli_reports_seeded_store(tmp_path: Path) -> None:
    cfg_path = _write_config(tmp_path)
    _seed_bars(tmp_path)
    cmd = f"{shlex.quote(sys.executable)} -m ai_mt5 store-health --config {shlex.quote(str(cfg_path))}"
    out = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=True)
    payload = json.loads(out.stdout.strip().splitlines()[-1])
    assert payload["bar_count"] == 3
    assert payload["earliest_open_time"] is not None
    assert payload["latest_open_time"] is not None
    assert payload["last_modified"] is not None
