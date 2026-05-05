"""Operator-facing health snapshot.

The health surface answers the question "is this system safe to trade
right now?" in one JSON blob:

* MT5 connection state (provided by an injected :class:`MT5StatusProvider`;
  defaults to ``DisconnectedMT5Status`` until the real terminal client
  arrives in #11).
* Last tick age (from audit trail).
* Open positions (from MT5 status provider; defaults to 0 offline).
* Kill switch state.
* Data freshness (from :class:`BarStore`).
* Model status (registered adapters + version).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

from ..audit.trail import AuditRecord, AuditTrail
from ..baseline.adapter import BaselineAdapter
from ..config.models import AppConfig
from ..data.bar_store import BarStore, FreshnessState, FreshnessStatus
from ..models.protocol import ModelAdapter
from ..risk.kill_switch import KillSwitch


class HealthStatus(StrEnum):
    """Aggregate verdict from the health snapshot."""

    OK = "ok"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass(frozen=True)
class MT5SnapshotData:
    """Plain payload shape the health surface expects from MT5."""

    connected: bool
    open_positions: int
    last_tick_at: datetime | None
    detail: str


class MT5StatusProvider(Protocol):
    """Plug point for the real MT5 status implementation in #11.

    Implementations MUST NOT raise; failure should be reported via
    ``connected=False`` and a ``detail`` describing the failure.
    """

    def snapshot(self, *, now: datetime) -> MT5SnapshotData: ...


class DisconnectedMT5Status:
    """Default offline implementation -- always reports disconnected."""

    def snapshot(self, *, now: datetime) -> MT5SnapshotData:
        return MT5SnapshotData(
            connected=False,
            open_positions=0,
            last_tick_at=None,
            detail="MT5 terminal not configured (offline build)",
        )


@dataclass(frozen=True)
class HealthSnapshot:
    """Single JSON-serialisable view used by ``ai-mt5 health``."""

    status: HealthStatus
    checked_at: datetime
    mt5: MT5SnapshotData
    kill_switch_engaged: bool
    last_tick_age_seconds: float | None
    last_tick_at: datetime | None
    data_freshness: FreshnessStatus
    open_positions: int
    models: list[dict[str, str]]
    issues: list[str]

    def to_dict(self) -> dict[str, Any]:
        lag = self.data_freshness.lag_bars
        return {
            "status": self.status.value,
            "checked_at": self.checked_at.isoformat(),
            "mt5": {
                "connected": self.mt5.connected,
                "open_positions": self.mt5.open_positions,
                "last_tick_at": (
                    self.mt5.last_tick_at.isoformat() if self.mt5.last_tick_at else None
                ),
                "detail": self.mt5.detail,
            },
            "kill_switch_engaged": self.kill_switch_engaged,
            "last_tick_age_seconds": self.last_tick_age_seconds,
            "last_tick_at": (self.last_tick_at.isoformat() if self.last_tick_at else None),
            "data_freshness": {
                "symbol": self.data_freshness.symbol,
                "timeframe": self.data_freshness.timeframe,
                "state": str(self.data_freshness.state),
                "lag_bars": None if lag == float("inf") else lag,
                "latest_open_time": (
                    self.data_freshness.latest_open_time.isoformat()
                    if self.data_freshness.latest_open_time
                    else None
                ),
            },
            "open_positions": self.open_positions,
            "models": list(self.models),
            "issues": list(self.issues),
        }


def _last_tick_record(records: list[AuditRecord]) -> AuditRecord | None:
    for record in reversed(records):
        if record.kind in {"tick.success", "tick.failure"}:
            return record
    return None


def _parse_iso(timestamp: str) -> datetime | None:
    try:
        return datetime.fromisoformat(timestamp)
    except ValueError:
        return None


def build_health(
    *,
    config: AppConfig,
    bar_store: BarStore,
    audit: AuditTrail,
    kill_switch: KillSwitch,
    adapters: list[ModelAdapter] | None = None,
    baseline: BaselineAdapter | None = None,
    mt5_status: MT5StatusProvider | None = None,
    now: datetime,
) -> HealthSnapshot:
    """Assemble a :class:`HealthSnapshot` from the deterministic components.

    The function is pure-ish: it reads the audit trail and store but
    never mutates them. The MT5 provider defaults to the offline
    disconnected stub.
    """
    primary = config.primary_symbol()
    freshness = bar_store.freshness(
        symbol=primary.symbol,
        timeframe=primary.timeframe,
        now=now,
        stale_after_bars=config.data_quality.stale_after_bars,
        expired_after_bars=config.data_quality.expired_after_bars,
    )
    mt5_provider = mt5_status or DisconnectedMT5Status()
    mt5 = mt5_provider.snapshot(now=now)

    records = audit.read_all()
    last_tick = _last_tick_record(records)
    last_tick_at = _parse_iso(last_tick.timestamp) if last_tick else None
    last_tick_age = (now - last_tick_at).total_seconds() if last_tick_at else None

    baseline_adapter = baseline or BaselineAdapter()
    model_entries: list[dict[str, str]] = [
        {"name": baseline_adapter.name, "version": baseline_adapter.version}
    ]
    for adapter in adapters or []:
        model_entries.append({"name": adapter.name, "version": adapter.version})

    issues: list[str] = []
    if freshness.state is FreshnessState.EXPIRED:
        issues.append(f"data_freshness=EXPIRED ({primary.symbol}/{primary.timeframe})")
    if freshness.state is FreshnessState.EMPTY:
        issues.append(f"data_freshness=EMPTY ({primary.symbol}/{primary.timeframe})")
    if kill_switch.is_engaged():
        issues.append("kill_switch_engaged")
    if not mt5.connected:
        issues.append(f"mt5_disconnected: {mt5.detail}")

    if not issues:
        status = HealthStatus.OK
    elif "kill_switch_engaged" in issues or any(
        i.startswith("data_freshness=EXPIRED") for i in issues
    ):
        status = HealthStatus.UNHEALTHY
    else:
        status = HealthStatus.DEGRADED

    return HealthSnapshot(
        status=status,
        checked_at=now,
        mt5=mt5,
        kill_switch_engaged=kill_switch.is_engaged(),
        last_tick_age_seconds=last_tick_age,
        last_tick_at=last_tick_at,
        data_freshness=freshness,
        open_positions=mt5.open_positions,
        models=model_entries,
        issues=issues,
    )
