"""Health snapshot assembled from data store, audit, kill switch."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ai_mt5.audit.trail import AuditRecord, JsonlAuditTrail
from ai_mt5.config.models import AppConfig
from ai_mt5.data.bar_store import BarStore
from ai_mt5.domain.bar import Bar
from ai_mt5.observability.health import (
    DisconnectedMT5Status,
    HealthStatus,
    MT5SnapshotData,
    build_health,
)
from ai_mt5.risk.kill_switch import InMemoryKillSwitch


@dataclass
class _FakeMT5:
    connected: bool = True
    open_positions: int = 0
    last_tick_at: datetime | None = None

    def snapshot(self, *, now: datetime) -> MT5SnapshotData:
        return MT5SnapshotData(
            connected=self.connected,
            open_positions=self.open_positions,
            last_tick_at=self.last_tick_at,
            detail="ok" if self.connected else "broker socket dropped",
        )


def _make_bar(ts: datetime) -> Bar:
    return Bar(
        symbol="EURUSD",
        timeframe="M15",
        open_time=ts,
        open=1.07,
        high=1.072,
        low=1.069,
        close=1.071,
        volume=1000.0,
        spread_points=10,
        is_closed=True,
    )


def _seed_store(store: BarStore, *, now: datetime, n: int = 30) -> None:
    bars = [_make_bar(now - timedelta(minutes=15 * (n - i))) for i in range(n)]
    store.append_many(bars)


def test_health_ok_when_data_fresh_and_kill_switch_off(
    app_config: AppConfig, tmp_path: Path
) -> None:
    now = datetime(2026, 4, 1, 12, 0, tzinfo=UTC)
    store = BarStore(app_config.storage.bars_path)
    _seed_store(store, now=now)

    audit = JsonlAuditTrail(Path(app_config.storage.audit_path) / "audit.jsonl")
    audit.append(
        AuditRecord(
            kind="tick.success",
            trace_id="t1",
            timestamp=(now - timedelta(seconds=30)).isoformat(),
            payload={},
        )
    )

    snapshot = build_health(
        config=app_config,
        bar_store=store,
        audit=audit,
        kill_switch=InMemoryKillSwitch(),
        mt5_status=_FakeMT5(connected=True),
        now=now,
    )
    assert snapshot.status is HealthStatus.OK
    assert snapshot.last_tick_age_seconds is not None
    assert 25 <= snapshot.last_tick_age_seconds <= 35
    assert snapshot.kill_switch_engaged is False
    assert snapshot.issues == []
    assert any(m["name"] == "baseline_sma_momentum" for m in snapshot.models)


def test_health_unhealthy_when_kill_switch_engaged(app_config: AppConfig, tmp_path: Path) -> None:
    now = datetime(2026, 4, 1, 12, 0, tzinfo=UTC)
    store = BarStore(app_config.storage.bars_path)
    _seed_store(store, now=now)
    audit = JsonlAuditTrail(Path(app_config.storage.audit_path) / "audit.jsonl")

    kill = InMemoryKillSwitch(engaged=True)
    snapshot = build_health(
        config=app_config,
        bar_store=store,
        audit=audit,
        kill_switch=kill,
        mt5_status=_FakeMT5(connected=True),
        now=now,
    )
    assert snapshot.status is HealthStatus.UNHEALTHY
    assert "kill_switch_engaged" in snapshot.issues


def test_health_unhealthy_when_data_expired(app_config: AppConfig, tmp_path: Path) -> None:
    now = datetime(2026, 4, 1, 12, 0, tzinfo=UTC)
    store = BarStore(app_config.storage.bars_path)
    # Last bar 50 hours back -> EXPIRED for M15.
    old = now - timedelta(hours=50)
    store.append_many([_make_bar(old)])
    audit = JsonlAuditTrail(Path(app_config.storage.audit_path) / "audit.jsonl")

    snapshot = build_health(
        config=app_config,
        bar_store=store,
        audit=audit,
        kill_switch=InMemoryKillSwitch(),
        mt5_status=_FakeMT5(connected=True),
        now=now,
    )
    assert snapshot.status is HealthStatus.UNHEALTHY
    assert any(i.startswith("data_freshness=EXPIRED") for i in snapshot.issues)


def test_health_degraded_when_only_mt5_disconnected(app_config: AppConfig, tmp_path: Path) -> None:
    now = datetime(2026, 4, 1, 12, 0, tzinfo=UTC)
    store = BarStore(app_config.storage.bars_path)
    _seed_store(store, now=now)
    audit = JsonlAuditTrail(Path(app_config.storage.audit_path) / "audit.jsonl")

    snapshot = build_health(
        config=app_config,
        bar_store=store,
        audit=audit,
        kill_switch=InMemoryKillSwitch(),
        mt5_status=_FakeMT5(connected=False),
        now=now,
    )
    assert snapshot.status is HealthStatus.DEGRADED
    assert any(i.startswith("mt5_disconnected") for i in snapshot.issues)


def test_default_mt5_status_reports_disconnected() -> None:
    snap = DisconnectedMT5Status().snapshot(now=datetime(2026, 4, 1, tzinfo=UTC))
    assert snap.connected is False
    assert snap.open_positions == 0
    assert "offline" in snap.detail


def test_to_dict_round_trips(app_config: AppConfig) -> None:
    now = datetime(2026, 4, 1, tzinfo=UTC)
    store = BarStore(app_config.storage.bars_path)
    _seed_store(store, now=now)
    audit = JsonlAuditTrail(Path(app_config.storage.audit_path) / "audit.jsonl")

    snapshot = build_health(
        config=app_config,
        bar_store=store,
        audit=audit,
        kill_switch=InMemoryKillSwitch(),
        mt5_status=_FakeMT5(connected=True),
        now=now,
    )
    payload = snapshot.to_dict()
    assert payload["status"] in {"ok", "degraded", "unhealthy"}
    assert payload["data_freshness"]["symbol"] == "EURUSD"
    assert payload["data_freshness"]["timeframe"] == "M15"
    assert isinstance(payload["models"], list)
