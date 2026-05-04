"""TickRunner populates metrics and fires alerts."""

from __future__ import annotations

from pathlib import Path

from ai_mt5.observability.alerts import AlertManager, AlertRule, Severity, default_rules
from ai_mt5.observability.metrics import (
    ERRORS,
    FORECASTS_EMITTED,
    LATENCY_MS,
    META_SIGNALS_EMITTED,
    RISK_DECISIONS,
    SPREAD_POINTS,
    MetricsRegistry,
)
from ai_mt5.risk.kill_switch import InMemoryKillSwitch
from ai_mt5.tick import TickRunner


def _names(snaps) -> list[str]:
    return [s.name for s in snaps]


def test_tick_increments_pipeline_counters(app_config, fixture_bars_path: Path) -> None:
    metrics = MetricsRegistry()
    runner = TickRunner(app_config, metrics=metrics)
    result = runner.run(bar_fixture_path=fixture_bars_path)
    assert result.status == "success"

    snaps = metrics.snapshot()
    forecasts = next(s for s in snaps if s.name == FORECASTS_EMITTED)
    meta = next(s for s in snaps if s.name == META_SIGNALS_EMITTED)
    risk = next(s for s in snaps if s.name == RISK_DECISIONS)
    spread = next(s for s in snaps if s.name == SPREAD_POINTS)
    latency = next(s for s in snaps if s.name == LATENCY_MS)
    assert forecasts.value == 1  # baseline only
    assert meta.value == 1
    assert risk.labels == {"outcome": "rejected"}  # record-only HOLD
    assert risk.value == 1
    assert spread.value > 0
    assert isinstance(latency.value, dict) and latency.value["count"] == 1


def test_tick_failure_increments_errors(app_config, tmp_path: Path) -> None:
    missing = tmp_path / "nope.csv"
    metrics = MetricsRegistry()
    runner = TickRunner(app_config, metrics=metrics)
    result = runner.run(bar_fixture_path=missing)
    assert result.status == "failure"
    snaps = metrics.snapshot()
    err = next(s for s in snaps if s.name == ERRORS)
    assert err.labels["kind"] in {"FileNotFoundError", "BarLoadError"}
    assert err.value == 1


def test_alerts_fire_when_kill_switch_engaged(app_config, fixture_bars_path: Path) -> None:
    kill = InMemoryKillSwitch(engaged=True)
    alerts = AlertManager(default_rules())
    runner = TickRunner(app_config, kill_switch=kill, alert_manager=alerts)
    runner.run(bar_fixture_path=fixture_bars_path)
    fired = [a.rule_id for a in alerts.fired]
    assert "kill_switch_engaged" in fired


def test_custom_alert_rule_fires(app_config, fixture_bars_path: Path) -> None:
    """Operator can plug new rules in via AlertManager."""
    fired_rules: list[str] = []
    rule = AlertRule(
        rule_id="forecasts_observed",
        severity=Severity.WARNING,
        cooldown=__import__("datetime").timedelta(seconds=1),
        evaluate=lambda payload: (
            ("any", "forecast cycle observed")
            if payload.get("freshness") in {"fresh", "stale", "expired", "empty"}
            else None
        ),
    )
    alerts = AlertManager([rule])
    alerts.subscribe(lambda a: fired_rules.append(a.rule_id))
    runner = TickRunner(app_config, alert_manager=alerts)
    runner.run(bar_fixture_path=fixture_bars_path)
    assert "forecasts_observed" in fired_rules
