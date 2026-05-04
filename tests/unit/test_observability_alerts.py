"""Alert severity, dedupe, and rule evaluation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ai_mt5.observability.alerts import (
    Alert,
    AlertManager,
    AlertRule,
    Severity,
    default_rules,
)


def _fired_keys(alerts: list[Alert]) -> list[str]:
    return [(a.rule_id, a.key) for a in alerts]


def test_rule_fires_once_within_cooldown() -> None:
    """A flapping signal must not produce duplicate alerts within cooldown."""
    rule = AlertRule(
        rule_id="data_expired",
        severity=Severity.ERROR,
        cooldown=timedelta(minutes=5),
        evaluate=lambda payload: ("EURUSD/M15", "expired") if payload.get("expired") else None,
    )
    manager = AlertManager([rule])
    t0 = datetime(2026, 4, 1, 12, 0, tzinfo=UTC)
    fired_a = manager.evaluate({"expired": True}, now=t0)
    fired_b = manager.evaluate({"expired": True}, now=t0 + timedelta(minutes=2))
    fired_c = manager.evaluate({"expired": True}, now=t0 + timedelta(minutes=6))
    assert len(fired_a) == 1
    assert fired_b == []
    assert len(fired_c) == 1


def test_dedupe_keys_are_independent_per_key() -> None:
    rule = AlertRule(
        rule_id="data_expired",
        severity=Severity.ERROR,
        cooldown=timedelta(minutes=10),
        evaluate=lambda payload: (
            payload["symbol"],
            f"{payload['symbol']} expired",
        ),
    )
    manager = AlertManager([rule])
    t0 = datetime(2026, 4, 1, tzinfo=UTC)
    fired_eu = manager.evaluate({"symbol": "EURUSD"}, now=t0)
    fired_gbp = manager.evaluate({"symbol": "GBPUSD"}, now=t0)
    assert len(fired_eu) == 1
    assert len(fired_gbp) == 1
    assert fired_eu[0].key != fired_gbp[0].key


def test_subscribers_receive_alerts() -> None:
    received: list[Alert] = []
    manager = AlertManager(default_rules(drawdown_threshold=0.04))
    manager.subscribe(received.append)
    t = datetime(2026, 4, 1, tzinfo=UTC)
    manager.evaluate({"drawdown_pct": 0.07}, now=t)
    manager.evaluate({"kill_switch_engaged": True}, now=t)
    keys = _fired_keys(received)
    assert ("drawdown_breach", "global") in keys
    assert ("kill_switch_engaged", "global") in keys


def test_no_alert_when_below_thresholds() -> None:
    manager = AlertManager(default_rules(drawdown_threshold=0.05))
    fired = manager.evaluate(
        {
            "drawdown_pct": 0.01,
            "kill_switch_engaged": False,
            "freshness": "fresh",
            "adapter_failure_rate": 0.1,
        },
        now=datetime(2026, 4, 1, tzinfo=UTC),
    )
    assert fired == []


def test_severity_round_trips_to_string() -> None:
    assert Severity.WARNING.value == "warning"
    assert Severity.ERROR.value == "error"
    assert Severity.CRITICAL.value == "critical"


def test_alert_to_dict_is_json_safe() -> None:
    rule = default_rules()[1]  # kill_switch_engaged
    manager = AlertManager([rule])
    fired = manager.evaluate({"kill_switch_engaged": True}, now=datetime(2026, 4, 1, tzinfo=UTC))
    payload = fired[0].to_dict()
    assert payload["rule_id"] == "kill_switch_engaged"
    assert payload["severity"] == "critical"
    assert "fired_at" in payload
