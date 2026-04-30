"""Issue #2: closed bar loader rejects Running Bars and bad data."""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path

import pytest

from ai_mt5.data import BarLoadError, load_closed_bars_csv

HEADER = "open_time,open,high,low,close,volume,spread_points,is_closed"


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "bars.csv"
    p.write_text(HEADER + "\n" + body, encoding="utf-8")
    return p


def test_loader_returns_sorted_bars(fixture_bars_path: Path) -> None:
    bars = load_closed_bars_csv(fixture_bars_path, symbol="EURUSD", timeframe="M15")
    assert len(bars) >= 20
    assert all(b.is_closed for b in bars)
    for prev, cur in pairwise(bars):
        assert cur.open_time > prev.open_time


def test_loader_rejects_running_bar(tmp_path: Path) -> None:
    body = (
        "2026-04-29T08:00:00+00:00,1.07,1.071,1.069,1.0705,1000,12,true\n"
        "2026-04-29T08:15:00+00:00,1.07,1.071,1.069,1.0705,1000,12,false\n"
    )
    with pytest.raises(BarLoadError, match="Running Bar"):
        load_closed_bars_csv(_write(tmp_path, body), symbol="EURUSD", timeframe="M15")


def test_loader_rejects_unsorted(tmp_path: Path) -> None:
    body = (
        "2026-04-29T08:15:00+00:00,1.07,1.071,1.069,1.0705,1000,12,true\n"
        "2026-04-29T08:00:00+00:00,1.07,1.071,1.069,1.0705,1000,12,true\n"
    )
    with pytest.raises(BarLoadError, match="strictly increasing"):
        load_closed_bars_csv(_write(tmp_path, body), symbol="EURUSD", timeframe="M15")


def test_loader_rejects_naive_timestamp(tmp_path: Path) -> None:
    body = "2026-04-29T08:00:00,1.07,1.071,1.069,1.0705,1000,12,true\n"
    with pytest.raises(BarLoadError, match="timezone-aware"):
        load_closed_bars_csv(_write(tmp_path, body), symbol="EURUSD", timeframe="M15")


def test_loader_rejects_missing_columns(tmp_path: Path) -> None:
    p = tmp_path / "bars.csv"
    p.write_text("open_time,close,is_closed\n2026-04-29T08:00:00+00:00,1.07,true\n")
    with pytest.raises(BarLoadError, match="missing columns"):
        load_closed_bars_csv(p, symbol="EURUSD", timeframe="M15")


def test_loader_rejects_empty(tmp_path: Path) -> None:
    p = tmp_path / "bars.csv"
    p.write_text(HEADER + "\n")
    with pytest.raises(BarLoadError, match="zero rows"):
        load_closed_bars_csv(p, symbol="EURUSD", timeframe="M15")
