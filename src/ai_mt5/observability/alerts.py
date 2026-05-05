"""Alert severity, dedupe, and a thin callback-based manager.

Alerts are operator-facing signals. They are intentionally separate from
audit records: an alert tells humans "look at this now", an audit entry
tells future readers "here is what happened". The same underlying event
may trigger both.

A rule is a pure function ``(payload) -> Alert | None`` evaluated against
each input. The :class:`AlertManager` deduplicates by ``(rule_id, key)``
within a configurable cooldown so a flapping signal doesn't drown the
operator.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any


class Severity(StrEnum):
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


def dedupe_key(rule_id: str, key: str) -> str:
    """Stable identity for a fired alert; used by :class:`AlertManager`."""
    return f"{rule_id}::{key}"


@dataclass(frozen=True)
class Alert:
    """A fired alert -- the manager passes one of these to each subscriber."""

    rule_id: str
    severity: Severity
    key: str
    message: str
    fired_at: datetime
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity.value,
            "key": self.key,
            "message": self.message,
            "fired_at": self.fired_at.isoformat(),
            "payload": self.payload,
        }


@dataclass(frozen=True)
class AlertRule:
    """Declarative rule fed to :class:`AlertManager`.

    Attributes:
        rule_id: Stable identifier (e.g. ``"data_expired"``).
        severity: Severity to attach when the rule fires.
        cooldown: Minimum gap between two firings of the same
            ``(rule_id, key)`` -- prevents flap.
        evaluate: ``(payload) -> (key, message) | None``. ``key`` lets the
            same rule fire independently for, say, two different symbols.
    """

    rule_id: str
    severity: Severity
    cooldown: timedelta
    evaluate: Callable[[dict[str, Any]], tuple[str, str] | None]


class AlertManager:
    """Collects fired alerts, dedupes by ``(rule_id, key)``, fans out to subscribers."""

    def __init__(self, rules: list[AlertRule] | None = None) -> None:
        self._rules: list[AlertRule] = list(rules or [])
        self._last_fired: dict[str, datetime] = {}
        self._subscribers: list[Callable[[Alert], None]] = []
        self._fired: list[Alert] = []

    def add_rule(self, rule: AlertRule) -> None:
        self._rules.append(rule)

    def subscribe(self, callback: Callable[[Alert], None]) -> None:
        self._subscribers.append(callback)

    @property
    def fired(self) -> list[Alert]:
        return list(self._fired)

    def evaluate(self, payload: dict[str, Any], *, now: datetime) -> list[Alert]:
        """Run every rule against ``payload``; return newly-fired alerts."""
        out: list[Alert] = []
        for rule in self._rules:
            outcome = rule.evaluate(payload)
            if outcome is None:
                continue
            key, message = outcome
            ddk = dedupe_key(rule.rule_id, key)
            last = self._last_fired.get(ddk)
            if last is not None and (now - last) < rule.cooldown:
                continue
            alert = Alert(
                rule_id=rule.rule_id,
                severity=rule.severity,
                key=key,
                message=message,
                fired_at=now,
                payload=dict(payload),
            )
            self._last_fired[ddk] = now
            self._fired.append(alert)
            out.append(alert)
            for sub in self._subscribers:
                sub(alert)
        return out


# -- canonical operator-facing rules ------------------------------------------


def _rule_data_expired() -> AlertRule:
    def evaluate(payload: dict[str, Any]) -> tuple[str, str] | None:
        if payload.get("freshness") != "expired":
            return None
        symbol = str(payload.get("symbol", "?"))
        timeframe = str(payload.get("timeframe", "?"))
        lag = payload.get("lag_bars")
        return (
            f"{symbol}/{timeframe}",
            f"data store EXPIRED for {symbol}/{timeframe} (lag_bars={lag})",
        )

    return AlertRule(
        rule_id="data_expired",
        severity=Severity.ERROR,
        cooldown=timedelta(minutes=5),
        evaluate=evaluate,
    )


def _rule_kill_switch_engaged() -> AlertRule:
    def evaluate(payload: dict[str, Any]) -> tuple[str, str] | None:
        if not payload.get("kill_switch_engaged"):
            return None
        return ("global", "kill switch engaged")

    return AlertRule(
        rule_id="kill_switch_engaged",
        severity=Severity.CRITICAL,
        cooldown=timedelta(minutes=1),
        evaluate=evaluate,
    )


def _rule_drawdown_breach(threshold: float = 0.05) -> AlertRule:
    def evaluate(payload: dict[str, Any]) -> tuple[str, str] | None:
        dd = float(payload.get("drawdown_pct", 0.0))
        if dd < threshold:
            return None
        return ("global", f"drawdown {dd:.2%} >= {threshold:.0%}")

    return AlertRule(
        rule_id="drawdown_breach",
        severity=Severity.ERROR,
        cooldown=timedelta(minutes=10),
        evaluate=evaluate,
    )


def _rule_adapter_failure_rate(threshold: float = 0.5) -> AlertRule:
    def evaluate(payload: dict[str, Any]) -> tuple[str, str] | None:
        rate = float(payload.get("adapter_failure_rate", 0.0))
        if rate < threshold:
            return None
        return ("global", f"adapter failure rate {rate:.0%} >= {threshold:.0%}")

    return AlertRule(
        rule_id="adapter_failure_rate",
        severity=Severity.WARNING,
        cooldown=timedelta(minutes=5),
        evaluate=evaluate,
    )


def default_rules(*, drawdown_threshold: float = 0.05) -> list[AlertRule]:
    """The canonical rule set plumbed into :class:`TickRunner`."""
    return [
        _rule_data_expired(),
        _rule_kill_switch_engaged(),
        _rule_drawdown_breach(threshold=drawdown_threshold),
        _rule_adapter_failure_rate(),
    ]
