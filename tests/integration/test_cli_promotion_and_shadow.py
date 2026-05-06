"""Issue #11 — ai-mt5 promotion-check and ai-mt5 shadow-report CLI."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml
from click.testing import CliRunner

from ai_mt5.cli import cli


def _write_config(tmp_path: Path, *, mode: str = "dry_run") -> Path:
    cfg_path = tmp_path / "config.yaml"
    cfg = {
        "environment": {"mode": mode, "timezone": "UTC", "log_level": "INFO"},
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


def test_promotion_check_emits_structured_json_with_failures(tmp_path: Path) -> None:
    """Demo target on a dry_run config must fail mode_allowed cleanly."""
    cfg_path = _write_config(tmp_path, mode="dry_run")
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    (reports_dir / "backtest.json").write_text("{}", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "promotion-check",
            "--config",
            str(cfg_path),
            "--target",
            "demo",
            "--reports-dir",
            str(reports_dir),
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 1
    payload = json.loads(result.output.strip().splitlines()[-1])
    assert payload["ok"] is False
    by_name = {c["name"]: c for c in payload["checks"]}
    assert by_name["mode_allowed"]["passed"] is False


def test_promotion_check_passes_for_aligned_demo_config(tmp_path: Path, monkeypatch) -> None:
    """Aligned config + secrets + recent backtest + known commit → ok=true."""
    cfg_path = _write_config(tmp_path, mode="demo")
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    (reports_dir / "backtest.json").write_text("{}", encoding="utf-8")
    for k in (
        "MT5_BRIDGE_HOST",
        "MT5_BRIDGE_PORT",
        "MT5_DEMO_LOGIN",
        "MT5_DEMO_PASSWORD",
        "MT5_DEMO_SERVER",
    ):
        monkeypatch.setenv(k, "set")
    # Make kill switch parent writable.
    (tmp_path / "STOP").parent.mkdir(parents=True, exist_ok=True)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "promotion-check",
            "--config",
            str(cfg_path),
            "--target",
            "demo",
            "--reports-dir",
            str(reports_dir),
        ],
        catch_exceptions=False,
    )
    payload = json.loads(result.output.strip().splitlines()[-1])
    assert result.exit_code == 0, payload
    assert payload["ok"] is True


def test_shadow_report_cli_round_trip(tmp_path: Path) -> None:
    """Build a tiny audit JSONL + bars CSV and verify shadow-report prints accuracy."""
    audit = tmp_path / "audit.jsonl"
    bars_csv = tmp_path / "bars.csv"

    t0 = datetime(2026, 4, 29, 12, 0, tzinfo=UTC)
    rows = [
        "open_time,open,high,low,close,volume,spread_points,is_closed",
    ]
    closes: list[float] = []
    for i in range(8):
        c = 1.0 + 0.0001 * i  # monotonically rising
        closes.append(c)
        ts = (t0 + timedelta(minutes=15 * i)).isoformat()
        rows.append(f"{ts},{c},{c + 0.0001},{c - 0.0001},{c},100,10,true")
    bars_csv.write_text("\n".join(rows) + "\n", encoding="utf-8")

    audit_events = [
        {
            "kind": "tick.start",
            "trace_id": "t1",
            "payload": {
                "mode": "shadow",
                "symbol": "EURUSD",
                "timeframe": "M15",
                "fixture": "live",
            },
        },
        {
            "kind": "tick.success",
            "trace_id": "t1",
            "payload": {
                "symbol": "EURUSD",
                "timeframe": "M15",
                "decision_time": t0.isoformat(),
                "forecast_direction": "BUY",
                "signal_direction": "BUY",
                "risk_approved": True,
                "risk_rejected_by": [],
                "completed_at": t0.isoformat(),
            },
        },
    ]
    audit.write_text("\n".join(json.dumps(e) for e in audit_events) + "\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "shadow-report",
            "--audit-log",
            str(audit),
            "--bars",
            str(bars_csv),
            "--symbol",
            "EURUSD",
            "--timeframe",
            "M15",
            "--horizon",
            "4",
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output.strip().splitlines()[-1])
    assert payload["n_decisions"] == 1
    assert payload["n_scored"] == 1
    assert payload["n_agreed"] == 1
    assert payload["accuracy"] == 1.0
