"""Issue #6: ingest() runs gates, blocks on blocking issues, persists otherwise."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from ai_mt5.data import BarStore, QualityConfig, ingest_bars
from ai_mt5.domain.bar import Bar


def _bars(n: int) -> list[Bar]:
    base = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
    dt = timedelta(minutes=15)
    return [
        Bar(
            symbol="EURUSD",
            timeframe="M15",
            open_time=base + i * dt,
            open=1.1,
            high=1.101,
            low=1.099,
            close=1.1005,
            volume=10.0,
            spread_points=5,
        )
        for i in range(n)
    ]


def test_ingest_writes_clean_bars(tmp_path: Path) -> None:
    store = BarStore(tmp_path)
    bars = _bars(6)
    result = ingest_bars(bars, store=store, symbol="EURUSD", timeframe="M15")
    assert result.ok
    assert result.bars_written == 6
    assert len(store.load(symbol="EURUSD", timeframe="M15")) == 6


def test_ingest_blocks_on_missing_bar_and_writes_nothing(tmp_path: Path) -> None:
    store = BarStore(tmp_path)
    bars = _bars(10)
    gapped = bars[:5] + bars[6:]  # drop one bar
    result = ingest_bars(gapped, store=store, symbol="EURUSD", timeframe="M15")
    assert not result.ok
    assert result.bars_written == 0
    assert store.load(symbol="EURUSD", timeframe="M15") == []


def test_ingest_warnings_do_not_block(tmp_path: Path) -> None:
    store = BarStore(tmp_path)
    bars = _bars(5)
    # Zero volume is a warning, not blocking.
    bars[2] = Bar(
        symbol=bars[2].symbol,
        timeframe=bars[2].timeframe,
        open_time=bars[2].open_time,
        open=bars[2].open,
        high=bars[2].high,
        low=bars[2].low,
        close=bars[2].close,
        volume=0.0,
        spread_points=bars[2].spread_points,
    )
    result = ingest_bars(bars, store=store, symbol="EURUSD", timeframe="M15")
    assert result.ok
    assert result.bars_written == 5
    assert any(w.code == "zero_volume" for w in result.report.warnings)


def test_ingest_respects_custom_spread_ceiling(tmp_path: Path) -> None:
    store = BarStore(tmp_path)
    bars = _bars(5)
    bars = [
        Bar(
            symbol=b.symbol,
            timeframe=b.timeframe,
            open_time=b.open_time,
            open=b.open,
            high=b.high,
            low=b.low,
            close=b.close,
            volume=b.volume,
            spread_points=500,
        )
        for b in bars
    ]
    cfg = QualityConfig(spread_max_points={"EURUSD": 30})
    result = ingest_bars(bars, store=store, symbol="EURUSD", timeframe="M15", config=cfg)
    assert result.ok  # warnings only
    assert any(w.code == "abnormal_spread" for w in result.report.warnings)
