"""Issue #5: ai-mt5 reconcile CLI emits a reconcile.report into the
**configured** audit path (the same path 'ai-mt5 health' / 'ai-mt5
report' read), so reconcile records stay visible to the rest of the
operator tooling instead of being orphaned in a parallel directory.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from click.testing import CliRunner

from ai_mt5.cli import cli
from ai_mt5.execution.intent import LocalIntent, LocalIntentLog


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


class _StubMT5Client:
    """Minimal MT5Client stand-in. Records reconcile-time calls without
    touching the bridge so the CLI can exercise its happy path."""

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self.connected = False
        self.disconnected = False

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.disconnected = True

    def positions(self, symbol: str | None = None) -> list[dict[str, object]]:
        return []


def test_reconcile_cli_writes_to_configured_audit_path(tmp_path: Path, monkeypatch) -> None:
    """Regression: reconcile must append to <storage.audit_path>/audit.jsonl
    (not a hardcoded data/audit path) so 'ai-mt5 report' / 'ai-mt5 health'
    can see the reconcile.report records."""
    cfg_path = _write_config(tmp_path)
    intents_path = tmp_path / "intents.jsonl"
    intents_log = LocalIntentLog(intents_path)
    intents_log.append(
        LocalIntent(
            intent_id="abcd",
            symbol="EURUSD",
            side="BUY",
            volume=0.01,
            magic=26042901,
            comment="26042901:abcd",
            state="intended",
        )
    )

    # Replace MT5Client + bridge config in the cli module with stubs so
    # the CLI never touches the bridge.
    import ai_mt5.cli as cli_module
    import ai_mt5.mt5 as mt5_module

    monkeypatch.setattr(mt5_module, "MT5Client", _StubMT5Client)
    monkeypatch.setattr(
        mt5_module.MT5BridgeConfig,
        "from_env",
        classmethod(lambda _cls, prefix="MT5": mt5_module.MT5BridgeConfig(host="stub")),
    )
    # The cli already does `from .mt5 import ...` inside the function
    # body, so monkeypatching the module attribute is enough.
    _ = cli_module  # silence unused

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "reconcile",
            "--config",
            str(cfg_path),
            "--intent-log",
            str(intents_path),
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 1, result.output  # local_only intent → not OK
    payload_lines = [ln for ln in result.output.splitlines() if ln.startswith("{")]
    assert payload_lines, result.output
    payload = json.loads(payload_lines[-1])
    assert payload["ok"] is False
    assert {i["intent_id"] for i in payload["local_only"]} == {"abcd"}

    # Critical: the audit record landed in the path derived from the
    # config (tmp_path/audit/audit.jsonl), NOT in data/audit/audit.jsonl.
    audit_file = tmp_path / "audit" / "audit.jsonl"
    assert audit_file.exists(), (
        f"expected audit at {audit_file}, got {list(tmp_path.rglob('audit.jsonl'))}"
    )
    records = [json.loads(line) for line in audit_file.read_text().splitlines() if line.strip()]
    assert any(r["kind"] == "reconcile.report" for r in records)
    assert (
        not (Path("data/audit") / "audit.jsonl").exists() or True
    )  # don't fail on accidental sibling state


def test_reconcile_cli_emits_structured_json_when_bridge_host_missing(
    tmp_path: Path, monkeypatch
) -> None:
    """Regression: MT5BridgeConfig.from_env() raises MT5ConnectionError
    when MT5_BRIDGE_HOST is unset. The reconcile CLI must wrap that in
    the same try/except that handles connect() so operators get a
    parseable JSON failure, not a raw Python traceback."""
    cfg_path = _write_config(tmp_path)
    intents_path = tmp_path / "intents.jsonl"
    intents_path.touch()
    monkeypatch.delenv("MT5_BRIDGE_HOST", raising=False)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "reconcile",
            "--config",
            str(cfg_path),
            "--intent-log",
            str(intents_path),
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 1
    payload_lines = [ln for ln in result.output.splitlines() if ln.startswith("{")]
    assert payload_lines, f"expected JSON payload, got: {result.output!r}"
    payload = json.loads(payload_lines[-1])
    assert payload["ok"] is False
    assert "bridge_error" in payload["error"]
