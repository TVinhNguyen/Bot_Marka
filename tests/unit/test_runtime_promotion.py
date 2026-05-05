"""Issue #11 — promotion checklist gates."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ai_mt5.config.models import AppConfig, RiskConfig, SymbolTimeframe
from ai_mt5.runtime.modes import RuntimeMode
from ai_mt5.runtime.promotion import (
    DEFAULT_REQUIRED_SECRETS,
    SMALL_LIVE_MAX_BASE_RISK_PCT,
    run_promotion_checks,
)

NOW = datetime(2026, 4, 29, 17, 0, tzinfo=UTC)


def _full_secret_env() -> dict[str, str]:
    return {name: "set" for name in DEFAULT_REQUIRED_SECRETS}


def _write_recent_report(reports_dir: Path, when: datetime = NOW) -> None:
    reports_dir.mkdir(parents=True, exist_ok=True)
    p = reports_dir / "backtest.json"
    p.write_text("{}", encoding="utf-8")
    ts = when.timestamp()
    import os

    os.utime(p, (ts, ts))


def test_passing_demo_promotion(
    app_config: AppConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = app_config.model_copy(
        update={"environment": app_config.environment.model_copy(update={"mode": "demo"})}
    )
    reports = tmp_path / "reports"
    _write_recent_report(reports)
    report = run_promotion_checks(
        config=cfg,
        target=RuntimeMode.DEMO,
        backtest_reports_dir=reports,
        now=NOW,
        env=_full_secret_env(),
        repo_root=Path(__file__).resolve().parents[2],
    )
    failed = [c.name for c in report.failures()]
    assert report.ok, f"unexpected failures: {failed}"
    assert {c.name for c in report.checks} == {
        "config_valid",
        "mode_allowed",
        "small_live_constraints",
        "secrets_present",
        "kill_switch_path",
        "audit_path_writable",
        "backtest_report_recent",
        "commit_known",
    }


def test_mode_mismatch_fails(app_config: AppConfig, tmp_path: Path) -> None:
    """Config says dry_run but operator wants demo → must fail."""
    reports = tmp_path / "reports"
    _write_recent_report(reports)
    report = run_promotion_checks(
        config=app_config,  # mode=dry_run
        target=RuntimeMode.DEMO,
        backtest_reports_dir=reports,
        now=NOW,
        env=_full_secret_env(),
    )
    assert report.ok is False
    by_name = {c.name: c for c in report.checks}
    assert by_name["mode_allowed"].passed is False
    assert "dry_run" in by_name["mode_allowed"].detail


def test_missing_secret_fails(app_config: AppConfig, tmp_path: Path) -> None:
    cfg = app_config.model_copy(
        update={"environment": app_config.environment.model_copy(update={"mode": "demo"})}
    )
    reports = tmp_path / "reports"
    _write_recent_report(reports)
    env = _full_secret_env()
    env.pop("MT5_DEMO_PASSWORD")
    report = run_promotion_checks(
        config=cfg,
        target=RuntimeMode.DEMO,
        backtest_reports_dir=reports,
        now=NOW,
        env=env,
    )
    assert report.ok is False
    by_name = {c.name: c for c in report.checks}
    assert by_name["secrets_present"].passed is False
    assert "MT5_DEMO_PASSWORD" in by_name["secrets_present"].detail


def test_small_live_requires_one_symbol(app_config: AppConfig, tmp_path: Path) -> None:
    """Issue #11: 'Small Live defaults enforce one symbol-timeframe.'"""
    reports = tmp_path / "reports"
    _write_recent_report(reports)
    risk = app_config.risk.model_copy(
        update={
            "base_risk_per_trade": 0.002,
            "max_daily_loss": 0.01,
            "max_total_drawdown": 0.03,
            "max_trades_per_day": 3,
        }
    )
    cfg = app_config.model_copy(
        update={
            "environment": app_config.environment.model_copy(update={"mode": "small_live"}),
            "symbols": [
                SymbolTimeframe(symbol="EURUSD", timeframe="M15", enabled=True),
                SymbolTimeframe(symbol="GBPUSD", timeframe="M15", enabled=True),
            ],
            "risk": risk,
        }
    )
    report = run_promotion_checks(
        config=cfg,
        target=RuntimeMode.SMALL_LIVE,
        backtest_reports_dir=reports,
        now=NOW,
        env=_full_secret_env(),
    )
    by_name = {c.name: c for c in report.checks}
    assert by_name["small_live_constraints"].passed is False
    assert "exactly one" in by_name["small_live_constraints"].detail


def test_small_live_caps_risk_envelope(app_config: AppConfig, tmp_path: Path) -> None:
    """base_risk above the small-live envelope must trip the gate."""
    reports = tmp_path / "reports"
    _write_recent_report(reports)
    risk = RiskConfig(
        base_risk_per_trade=SMALL_LIVE_MAX_BASE_RISK_PCT * 2,
        max_risk_per_trade=SMALL_LIVE_MAX_BASE_RISK_PCT * 2,
        min_risk_per_trade=SMALL_LIVE_MAX_BASE_RISK_PCT,
        max_daily_loss=0.01,
        max_total_drawdown=0.03,
        max_positions_per_symbol=1,
        max_total_positions=1,
        max_trades_per_day=3,
        max_consecutive_losses=3,
        sl_atr_min=1.0,
        sl_atr_max=2.0,
        tp_atr=1.5,
        rr_min=1.0,
        margin_safety=0.8,
        kill_switch_file=str(tmp_path / "STOP"),
    )
    cfg = app_config.model_copy(
        update={
            "environment": app_config.environment.model_copy(update={"mode": "small_live"}),
            "symbols": [SymbolTimeframe(symbol="EURUSD", timeframe="M15", enabled=True)],
            "risk": risk,
        }
    )
    report = run_promotion_checks(
        config=cfg,
        target=RuntimeMode.SMALL_LIVE,
        backtest_reports_dir=reports,
        now=NOW,
        env=_full_secret_env(),
    )
    by_name = {c.name: c for c in report.checks}
    assert by_name["small_live_constraints"].passed is False
    assert "base_risk_per_trade" in by_name["small_live_constraints"].detail


def test_stale_backtest_fails(app_config: AppConfig, tmp_path: Path) -> None:
    cfg = app_config.model_copy(
        update={"environment": app_config.environment.model_copy(update={"mode": "demo"})}
    )
    reports = tmp_path / "reports"
    _write_recent_report(reports, when=NOW - timedelta(days=30))
    report = run_promotion_checks(
        config=cfg,
        target=RuntimeMode.DEMO,
        backtest_reports_dir=reports,
        backtest_max_age_days=7,
        now=NOW,
        env=_full_secret_env(),
    )
    by_name = {c.name: c for c in report.checks}
    assert by_name["backtest_report_recent"].passed is False
    assert "30d" in by_name["backtest_report_recent"].detail


def test_unknown_commit_fails(app_config: AppConfig, tmp_path: Path) -> None:
    """Refusing to promote when we cannot resolve a real commit SHA."""
    cfg = app_config.model_copy(
        update={"environment": app_config.environment.model_copy(update={"mode": "demo"})}
    )
    reports = tmp_path / "reports"
    _write_recent_report(reports)
    report = run_promotion_checks(
        config=cfg,
        target=RuntimeMode.DEMO,
        backtest_reports_dir=reports,
        now=NOW,
        env=_full_secret_env(),
        repo_root=tmp_path,  # no .git here
    )
    by_name = {c.name: c for c in report.checks}
    assert by_name["commit_known"].passed is False


def test_report_to_dict_is_json_safe(app_config: AppConfig, tmp_path: Path) -> None:
    import json

    cfg = app_config.model_copy(
        update={"environment": app_config.environment.model_copy(update={"mode": "demo"})}
    )
    reports = tmp_path / "reports"
    _write_recent_report(reports)
    report = run_promotion_checks(
        config=cfg,
        target=RuntimeMode.DEMO,
        backtest_reports_dir=reports,
        now=NOW,
        env=_full_secret_env(),
    )
    payload = report.to_dict()
    json.dumps(payload, sort_keys=True)
    assert set(payload.keys()) == {"ok", "target", "snapshot", "checks"}
