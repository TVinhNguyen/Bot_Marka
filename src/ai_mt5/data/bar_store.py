"""Local market-data store for Closed Bars.

This module is the persistence layer for issue #6. One file per
symbol-timeframe, JSONL encoded, one Closed Bar per line. The contract:

* **Append-only**: existing rows are never rewritten. Re-appending the same
  ``open_time`` is a no-op (idempotent ingest).
* **UTC-only**: ``open_time`` is always serialized as an ISO-8601 UTC string;
  on read the loader rejects naive timestamps.
* **Deterministic replay**: :meth:`BarStore.load` returns bars strictly
  sorted by ``open_time`` so downstream replay/backtest code needs no
  re-sorting.

A tiny :class:`FreshnessStatus` helper exposes "fresh / stale / expired"
so the tick runner and the health endpoint can share the same definition.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from ..domain.bar import Bar
from .bar_loader import BarLoadError
from .timeframe import timeframe_delta


def _isoformat_utc(ts: datetime) -> str:
    return ts.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_utc(raw: str) -> datetime:
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    ts = datetime.fromisoformat(raw)
    if ts.tzinfo is None:
        raise BarLoadError(f"stored open_time {raw!r} is naive (UTC required)")
    return ts.astimezone(UTC)


def _bar_to_line(bar: Bar) -> str:
    payload = {
        "symbol": bar.symbol,
        "timeframe": bar.timeframe,
        "open_time": _isoformat_utc(bar.open_time),
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "volume": bar.volume,
        "spread_points": bar.spread_points,
    }
    return json.dumps(payload, sort_keys=True)


def _line_to_bar(raw: str, *, default_symbol: str, default_timeframe: str) -> Bar:
    rec = json.loads(raw)
    return Bar(
        symbol=str(rec.get("symbol", default_symbol)),
        timeframe=str(rec.get("timeframe", default_timeframe)),
        open_time=_parse_utc(str(rec["open_time"])),
        open=float(rec["open"]),
        high=float(rec["high"]),
        low=float(rec["low"]),
        close=float(rec["close"]),
        volume=float(rec["volume"]),
        spread_points=int(rec.get("spread_points", 0) or 0),
        is_closed=True,
    )


class FreshnessState(StrEnum):
    """Severity of how old the newest bar is."""

    FRESH = "fresh"
    STALE = "stale"
    EXPIRED = "expired"
    EMPTY = "empty"


@dataclass(frozen=True)
class FreshnessStatus:
    """Snapshot of how current a symbol-timeframe's data is."""

    symbol: str
    timeframe: str
    state: FreshnessState
    latest_open_time: datetime | None
    checked_at: datetime
    lag_bars: float  # how many bars behind ``now`` the latest bar is

    @property
    def ok(self) -> bool:
        """True iff the latest bar is ``FRESH``.

        Callers that want to allow slightly stale data should inspect
        :attr:`lag_bars` directly instead.
        """
        return self.state is FreshnessState.FRESH


class BarStore:
    """JSONL-backed append-only bar store for one symbol-timeframe.

    Path layout: ``{root}/{symbol}_{timeframe}.jsonl``. Each file is
    self-describing so downstream tooling can read it without consulting
    a manifest.
    """

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    # -- path helpers --------------------------------------------------------

    def path_for(self, symbol: str, timeframe: str) -> Path:
        return self._root / f"{symbol}_{timeframe}.jsonl"

    def exists(self, symbol: str, timeframe: str) -> bool:
        return self.path_for(symbol, timeframe).exists()

    # -- write ---------------------------------------------------------------

    def append_many(self, bars: list[Bar]) -> int:
        """Append ``bars`` to the per-symbol-timeframe file.

        * Skips rows whose ``open_time`` is already stored (idempotent).
        * Rejects mixed symbol/timeframe batches (callers must split first).
        * Returns the number of rows actually written.
        """
        if not bars:
            return 0
        symbols = {b.symbol for b in bars}
        timeframes = {b.timeframe for b in bars}
        if len(symbols) != 1 or len(timeframes) != 1:
            raise ValueError(
                "append_many requires a single symbol/timeframe; "
                f"got symbols={sorted(symbols)}, timeframes={sorted(timeframes)}"
            )
        symbol = next(iter(symbols))
        timeframe = next(iter(timeframes))

        existing = {b.open_time for b in self.load(symbol=symbol, timeframe=timeframe)}
        fresh = sorted(
            (b for b in bars if b.open_time not in existing),
            key=lambda b: b.open_time,
        )
        if not fresh:
            return 0
        path = self.path_for(symbol, timeframe)
        with path.open("a", encoding="utf-8") as fp:
            for bar in fresh:
                fp.write(_bar_to_line(bar) + "\n")
            fp.flush()
            os.fsync(fp.fileno())
        return len(fresh)

    # -- read ----------------------------------------------------------------

    def load(self, *, symbol: str, timeframe: str) -> list[Bar]:
        """Return every stored bar, sorted by ``open_time`` ascending."""
        path = self.path_for(symbol, timeframe)
        if not path.exists():
            return []
        out: list[Bar] = []
        with path.open("r", encoding="utf-8") as fp:
            for lineno, line in enumerate(fp, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    out.append(
                        _line_to_bar(
                            stripped,
                            default_symbol=symbol,
                            default_timeframe=timeframe,
                        )
                    )
                except (KeyError, ValueError, json.JSONDecodeError) as exc:
                    raise BarLoadError(f"{path}:{lineno} is malformed: {exc}") from exc
        out.sort(key=lambda b: b.open_time)
        return out

    def latest(self, *, symbol: str, timeframe: str) -> Bar | None:
        bars = self.load(symbol=symbol, timeframe=timeframe)
        return bars[-1] if bars else None

    # -- freshness -----------------------------------------------------------

    def freshness(
        self,
        *,
        symbol: str,
        timeframe: str,
        now: datetime,
        stale_after_bars: float = 1.0,
        expired_after_bars: float = 2.0,
    ) -> FreshnessStatus:
        """Report how current the stored data is for ``symbol`` / ``timeframe``.

        ``stale_after_bars`` and ``expired_after_bars`` express the thresholds
        in units of *bar length* for ``timeframe`` so the definitions scale
        with the configured interval.
        """
        latest = self.latest(symbol=symbol, timeframe=timeframe)
        if latest is None:
            return FreshnessStatus(
                symbol=symbol,
                timeframe=timeframe,
                state=FreshnessState.EMPTY,
                latest_open_time=None,
                checked_at=now,
                lag_bars=float("inf"),
            )
        dt = timeframe_delta(timeframe)
        lag = (now - latest.open_time).total_seconds() / dt.total_seconds()
        if lag >= expired_after_bars:
            state = FreshnessState.EXPIRED
        elif lag >= stale_after_bars:
            state = FreshnessState.STALE
        else:
            state = FreshnessState.FRESH
        return FreshnessStatus(
            symbol=symbol,
            timeframe=timeframe,
            state=state,
            latest_open_time=latest.open_time,
            checked_at=now,
            lag_bars=max(lag, 0.0),
        )
