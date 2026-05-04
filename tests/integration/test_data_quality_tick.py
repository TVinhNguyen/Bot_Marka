"""Issue #6: TickRunner wires quality gates + freshness into the pipeline."""

from __future__ import annotations

from pathlib import Path

from ai_mt5.audit import JsonlAuditTrail
from ai_mt5.data import BarStore, FreshnessState
from ai_mt5.tick import TickRunner


def test_tick_audits_data_quality_and_freshness(app_config, fixture_bars_path: Path) -> None:
    """A healthy fixture tick emits data_quality + data_freshness records."""
    runner = TickRunner(app_config)
    result = runner.run(bar_fixture_path=fixture_bars_path)
    assert result.status == "success"
    assert result.data_quality is not None and result.data_quality.ok
    assert result.data_freshness is not None

    records = JsonlAuditTrail(Path(app_config.storage.audit_path) / "audit.jsonl").read_all()
    kinds = [r.kind for r in records]
    assert "data_quality" in kinds
    assert "data_freshness" in kinds


def test_tick_blocks_when_fixture_has_missing_bars(
    app_config, tmp_path: Path, fixture_bars_path: Path
) -> None:
    """Dropping a bar in the middle of the fixture must fail the tick."""
    gapped = tmp_path / "gapped.csv"
    lines = fixture_bars_path.read_text(encoding="utf-8").splitlines()
    header = lines[0]
    body = lines[1:]
    # Drop one in the middle -> introduces a 30-minute gap on M15 data.
    body.pop(len(body) // 2)
    gapped.write_text("\n".join([header, *body]) + "\n", encoding="utf-8")

    runner = TickRunner(app_config)
    result = runner.run(bar_fixture_path=gapped)
    assert result.status == "failure"
    assert "missing_bars" in (result.error or "") or "gap" in (result.error or "").lower()


def test_runner_freshness_helper_reflects_store(app_config, fixture_bars_path: Path) -> None:
    """``TickRunner.freshness`` reads from the BarStore the tick ingests into."""
    runner = TickRunner(app_config)
    # Ingest fixture into the store first.
    from ai_mt5.data import load_closed_bars_csv

    bars = load_closed_bars_csv(
        fixture_bars_path,
        symbol=app_config.primary_symbol().symbol,
        timeframe=app_config.primary_symbol().timeframe,
    )
    report = runner.ingest(bars)
    assert report.ok

    # Now freshness at the last bar's time should be FRESH.
    fresh = runner.freshness(now=bars[-1].open_time)
    assert fresh.state is FreshnessState.FRESH

    # Far-future -> EXPIRED.
    far_future = bars[-1].open_time.replace(year=2099)
    expired = runner.freshness(now=far_future)
    assert expired.state is FreshnessState.EXPIRED


def test_tick_does_not_crash_when_store_is_empty(app_config, fixture_bars_path: Path) -> None:
    """Freshness against an empty store is EMPTY; fixture's own bars satisfy the tick."""
    # We never call ingest() first -> store is empty.
    store_root = Path(app_config.storage.bars_path)
    assert not any(store_root.glob("*.jsonl")) or not BarStore(store_root).load(
        symbol=app_config.primary_symbol().symbol,
        timeframe=app_config.primary_symbol().timeframe,
    )
    runner = TickRunner(app_config)
    result = runner.run(bar_fixture_path=fixture_bars_path)
    # Fixture-only tick sets freshness against fixture latest_ts, which ignores the store.
    # But the freshness helper wrapper reads from the store; ensure no crash either way.
    assert result.status == "success"


def test_fixture_tick_not_blocked_by_stale_store(app_config, fixture_bars_path: Path) -> None:
    """Pre-existing stale store data must NOT block a fixture-only tick.

    The store is the source of truth only for ``--from-store`` replay.
    When the operator runs the smoke-test fixture path, the bars from the
    CSV are authoritative and the local store may legitimately be empty
    or arbitrarily out of date.
    """
    from datetime import UTC, datetime, timedelta

    from ai_mt5.data import BarStore
    from ai_mt5.domain.bar import Bar

    # Seed the store with one ancient bar so freshness against the fixture's
    # last bar is EXPIRED.
    sym = app_config.primary_symbol()
    store = BarStore(app_config.storage.bars_path)
    ancient = datetime(1970, 1, 1, tzinfo=UTC)
    store.append_many(
        [
            Bar(
                symbol=sym.symbol,
                timeframe=sym.timeframe,
                open_time=ancient + timedelta(minutes=15 * i),
                open=1.0,
                high=1.0,
                low=1.0,
                close=1.0,
                volume=1.0,
                spread_points=0,
            )
            for i in range(2)
        ]
    )

    runner = TickRunner(app_config)
    result = runner.run(bar_fixture_path=fixture_bars_path)
    assert result.status == "success", result.error


def test_audit_freshness_records_null_lag_for_empty_store(
    app_config, fixture_bars_path: Path
) -> None:
    """``lag_bars`` must serialise as JSON null, not the invalid ``Infinity``."""
    import json

    runner = TickRunner(app_config)
    runner.run(bar_fixture_path=fixture_bars_path)

    audit_path = Path(app_config.storage.audit_path) / "audit.jsonl"
    raw = audit_path.read_text(encoding="utf-8")
    # Every line must round-trip through standard JSON (no ``Infinity`` token).
    assert "Infinity" not in raw
    records = [json.loads(line) for line in raw.splitlines() if line.strip()]
    fresh = [r for r in records if r.get("kind") == "data_freshness"]
    assert fresh, "expected a data_freshness audit record"
    assert fresh[0]["payload"]["lag_bars"] is None
