"""Issue #9: TickRunner with an Ensemble over Baseline + offline adapters."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ai_mt5.audit import JsonlAuditTrail
from ai_mt5.config.models import AppConfig
from ai_mt5.data.bar_store import BarStore
from ai_mt5.data.forecast_store import JsonlForecastStore
from ai_mt5.ensemble import Ensemble, EnsembleConfig
from ai_mt5.models import ChronosAdapter, KronosAdapter, TimesFMAdapter
from ai_mt5.risk.kill_switch import FileKillSwitch
from ai_mt5.text.event_risk import EventRiskAdapter
from ai_mt5.text.news import NewsEvent, NewsStore
from ai_mt5.tick import TickRunner


def _build_runner(app_config: AppConfig, *, event_risk: EventRiskAdapter | None) -> TickRunner:
    audit = JsonlAuditTrail(Path(app_config.storage.audit_path) / "audit.jsonl")
    return TickRunner(
        app_config,
        audit=audit,
        forecast_store=JsonlForecastStore(
            Path(app_config.storage.forecasts_path) / "forecasts.jsonl"
        ),
        kill_switch=FileKillSwitch(app_config.risk.kill_switch_file),
        bar_store=BarStore(app_config.storage.bars_path),
        adapters=[TimesFMAdapter(), KronosAdapter(), ChronosAdapter()],
        ensemble=Ensemble(EnsembleConfig(min_models=1)),
        event_risk=event_risk,
    )


def test_ensemble_tick_audits_every_component_forecast(
    app_config: AppConfig, fixture_bars_path: Path
) -> None:
    runner = _build_runner(app_config, event_risk=None)
    result = runner.run(bar_fixture_path=fixture_bars_path)
    assert result.status == "success"

    audit_lines = (Path(app_config.storage.audit_path) / "audit.jsonl").read_text().splitlines()
    kinds = [json.loads(line)["kind"] for line in audit_lines]
    forecast_kinds = [k for k in kinds if k == "forecast"]
    # Baseline + TimesFM + Kronos + Chronos.
    assert len(forecast_kinds) == 4
    assert "meta_signal" in kinds


def test_ensemble_event_risk_veto_blocks_trade(
    app_config: AppConfig, fixture_bars_path: Path, tmp_path: Path
) -> None:
    """A high-impact news event within the fixture's decision window must veto."""
    # Decision bar in the shipped fixture is at 2026-04-29T13:45Z. Put a news
    # event 5 minutes earlier so it is inside the default 24h recency window.
    news = NewsStore(tmp_path / "news.jsonl")
    news.append(
        NewsEvent(
            event_id="nfp",
            symbol="EURUSD",
            scheduled_at=datetime(2026, 4, 29, 13, 40, tzinfo=UTC),
            impact="high",
            title="central bank shock hawkish surprise",
        )
    )
    event_risk = EventRiskAdapter(news)
    runner = _build_runner(app_config, event_risk=event_risk)

    result = runner.run(bar_fixture_path=fixture_bars_path)
    assert result.status == "success"

    records = [
        json.loads(line)
        for line in (Path(app_config.storage.audit_path) / "audit.jsonl").read_text().splitlines()
    ]
    event_records = [r for r in records if r["kind"] == "event_risk"]
    assert event_records
    assert not event_records[0]["payload"]["trade_permission"]

    meta_records = [r for r in records if r["kind"] == "meta_signal"]
    assert meta_records
    veto = meta_records[0]["payload"]["veto_reasons"]
    assert "high_event_risk" in veto or "event_risk_no_permission" in veto


def test_event_risk_permits_trade_when_news_window_is_clean(
    app_config: AppConfig, fixture_bars_path: Path, tmp_path: Path
) -> None:
    """With a calm, stale-free news fixture, the Ensemble is not vetoed by Event Risk."""
    news = NewsStore(tmp_path / "news.jsonl")
    news.append(
        NewsEvent(
            event_id="calm",
            symbol="EURUSD",
            scheduled_at=datetime(2026, 4, 29, 13, 30, tzinfo=UTC),
            impact="low",
            title="stable outlook growth continues",
        )
    )
    runner = _build_runner(
        app_config,
        event_risk=EventRiskAdapter(
            news, recency_window=timedelta(hours=24), stale_after=timedelta(days=30)
        ),
    )
    result = runner.run(bar_fixture_path=fixture_bars_path)
    assert result.status == "success"
    records = [
        json.loads(line)
        for line in (Path(app_config.storage.audit_path) / "audit.jsonl").read_text().splitlines()
    ]
    event_records = [r for r in records if r["kind"] == "event_risk"]
    assert event_records
    assert event_records[0]["payload"]["trade_permission"]
