"""Closed Bar loader for fixture data.

Fixtures are stored as CSV files under ``data/fixtures/bars`` with the
columns:

    open_time,open,high,low,close,volume,spread_points,is_closed

The loader rejects rows whose ``is_closed`` flag is ``False`` so that no
Running Bar can ever leak into feature generation or a forecast.
"""

from __future__ import annotations

import csv
import os
from datetime import datetime
from itertools import pairwise
from pathlib import Path

from ..domain.bar import Bar


class BarLoadError(ValueError):
    """Raised when fixture bar data is missing, malformed, or contains a Running Bar."""


def _parse_iso(value: str) -> datetime:
    # Accept both "...Z" and "+00:00" forms; reject naive timestamps.
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    ts = datetime.fromisoformat(value)
    if ts.tzinfo is None:
        raise BarLoadError(f"open_time {value!r} must be timezone-aware (UTC)")
    return ts


def _parse_bool(value: str) -> bool:
    v = value.strip().lower()
    if v in {"true", "1", "yes"}:
        return True
    if v in {"false", "0", "no"}:
        return False
    raise BarLoadError(f"is_closed must be true/false, got {value!r}")


def load_closed_bars_csv(
    path: str | os.PathLike[str],
    *,
    symbol: str,
    timeframe: str,
) -> list[Bar]:
    """Load a CSV of bars for ``symbol``/``timeframe``.

    Returns the bars sorted by ``open_time`` ascending. Raises
    :class:`BarLoadError` for any structural problem (missing file, missing
    columns, Running Bar, unsorted timestamps, NaN OHLCV).
    """
    p = Path(path)
    if not p.exists():
        raise BarLoadError(f"bar fixture not found: {p}")

    required = {"open_time", "open", "high", "low", "close", "volume", "is_closed"}
    bars: list[Bar] = []
    with p.open("r", encoding="utf-8") as fp:
        reader = csv.DictReader(fp)
        if reader.fieldnames is None or not required.issubset(set(reader.fieldnames)):
            missing = required - set(reader.fieldnames or [])
            raise BarLoadError(f"bar fixture {p} missing columns: {sorted(missing)}")
        for idx, row in enumerate(reader, start=2):  # start=2 -> account for header
            try:
                is_closed = _parse_bool(row["is_closed"])
                if not is_closed:
                    raise BarLoadError(
                        f"row {idx} in {p} is a Running Bar; only Closed Bars allowed"
                    )
                bar = Bar(
                    symbol=symbol,
                    timeframe=timeframe,
                    open_time=_parse_iso(row["open_time"]),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                    spread_points=int(row.get("spread_points", "0") or 0),
                    is_closed=True,
                )
            except BarLoadError:
                raise
            except (KeyError, ValueError) as exc:
                raise BarLoadError(f"row {idx} in {p} is invalid: {exc}") from exc
            bars.append(bar)

    if not bars:
        raise BarLoadError(f"bar fixture {p} contained zero rows")

    # Continuity check: timestamps must be strictly increasing.
    for prev, cur in pairwise(bars):
        if cur.open_time <= prev.open_time:
            raise BarLoadError(
                f"bars in {p} are not strictly increasing in time "
                f"({prev.open_time.isoformat()} -> {cur.open_time.isoformat()})"
            )
    return bars
