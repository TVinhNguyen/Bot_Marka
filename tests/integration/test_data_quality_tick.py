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
