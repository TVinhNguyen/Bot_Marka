"""Issue #6: BarStore round trip, append-only, freshness."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ai_mt5.data import BarLoadError, BarStore, FreshnessState
from ai_mt5.domain.bar import Bar


def _bar(minute: int, *, symbol: str = "EURUSD", timeframe: str = "M15") -> Bar:
    base = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
    return Bar(
        symbol=symbol,
        timeframe=timeframe,
        open_time=base + timedelta(minutes=minute * 15),
        open=1.1000,
        high=1.1010,
        low=1.0990,
        close=1.1005,
        volume=100.0,
        spread_points=5,
    )


def test_round_trip_preserves_fields(tmp_path: Path) -> None:
    store = BarStore(tmp_path)
    bars = [_bar(i) for i in range(5)]
    assert store.append_many(bars) == 5
    loaded = store.load(symbol="EURUSD", timeframe="M15")
    assert loaded == bars


def test_append_is_idempotent(tmp_path: Path) -> None:
    """Re-appending the same open_time writes zero rows."""
    store = BarStore(tmp_path)
    bars = [_bar(i) for i in range(3)]
    assert store.append_many(bars) == 3
    assert store.append_many(bars) == 0
    assert store.append_many([_bar(3)]) == 1
    assert len(store.load(symbol="EURUSD", timeframe="M15")) == 4


def test_load_sorts_by_open_time(tmp_path: Path) -> None:
    store = BarStore(tmp_path)
    store.append_many([_bar(2), _bar(0), _bar(1)])
    loaded = store.load(symbol="EURUSD", timeframe="M15")
    times = [b.open_time for b in loaded]
    assert times == sorted(times)


def test_mixed_symbol_batch_rejected(tmp_path: Path) -> None:
    store = BarStore(tmp_path)
    with pytest.raises(ValueError, match="single symbol"):
        store.append_many([_bar(0), _bar(1, symbol="GBPUSD")])


def test_freshness_empty_when_no_bars(tmp_path: Path) -> None:
    store = BarStore(tmp_path)
    now = datetime(2024, 1, 1, tzinfo=UTC)
    status = store.freshness(symbol="EURUSD", timeframe="M15", now=now)
    assert status.state is FreshnessState.EMPTY
    assert status.latest_open_time is None


def test_freshness_fresh_stale_expired(tmp_path: Path) -> None:
    store = BarStore(tmp_path)
    # latest bar at 10:00 UTC, M15 = 15 minute bars.
    latest_ts = datetime(2024, 1, 1, 10, 0, tzinfo=UTC)
    store.append_many(
        [
            Bar(
                symbol="EURUSD",
                timeframe="M15",
                open_time=latest_ts,
                open=1.1,
                high=1.11,
                low=1.09,
                close=1.10,
                volume=10.0,
                spread_points=1,
            )
        ]
    )

    fresh_now = latest_ts + timedelta(minutes=10)
    stale_now = latest_ts + timedelta(minutes=20)
    expired_now = latest_ts + timedelta(minutes=40)

    fresh = store.freshness(symbol="EURUSD", timeframe="M15", now=fresh_now)
    stale = store.freshness(symbol="EURUSD", timeframe="M15", now=stale_now)
    expired = store.freshness(symbol="EURUSD", timeframe="M15", now=expired_now)

    assert fresh.state is FreshnessState.FRESH
    assert stale.state is FreshnessState.STALE
    assert expired.state is FreshnessState.EXPIRED
    assert expired.lag_bars > 2.0


def test_malformed_store_file_raises(tmp_path: Path) -> None:
    store = BarStore(tmp_path)
    path = store.path_for("EURUSD", "M15")
    path.write_text("not json\n", encoding="utf-8")
    with pytest.raises(BarLoadError):
        store.load(symbol="EURUSD", timeframe="M15")


def test_health_for_empty_store(tmp_path: Path) -> None:
    store = BarStore(tmp_path)
    now = datetime(2024, 1, 1, 5, 0, tzinfo=UTC)
    health = store.health(symbol="EURUSD", timeframe="M15", now=now)
    assert health.bar_count == 0
    assert health.earliest_open_time is None
    assert health.latest_open_time is None
    assert health.last_modified is None
    assert health.freshness.state is FreshnessState.EMPTY
    assert health.to_dict()["ok"] is False


def test_health_reports_count_and_window(tmp_path: Path) -> None:
    store = BarStore(tmp_path)
    bars = [_bar(i) for i in range(4)]
    store.append_many(bars)
    now = bars[-1].open_time + timedelta(minutes=5)
    health = store.health(symbol="EURUSD", timeframe="M15", now=now)
    assert health.bar_count == 4
    assert health.earliest_open_time == bars[0].open_time
    assert health.latest_open_time == bars[-1].open_time
    assert health.last_modified is not None
    assert health.freshness.state is FreshnessState.FRESH
    payload = health.to_dict()
    assert payload["symbol"] == "EURUSD"
    assert payload["timeframe"] == "M15"
    assert payload["bar_count"] == 4
    assert payload["freshness"]["state"] == "fresh"
    assert payload["ok"] is True


def test_health_marks_expired_when_lag_exceeds_threshold(tmp_path: Path) -> None:
    store = BarStore(tmp_path)
    bars = [_bar(i) for i in range(2)]
    store.append_many(bars)
    far_future = bars[-1].open_time + timedelta(minutes=15 * 5)
    health = store.health(symbol="EURUSD", timeframe="M15", now=far_future)
    assert health.freshness.state is FreshnessState.EXPIRED
    assert health.to_dict()["ok"] is False
