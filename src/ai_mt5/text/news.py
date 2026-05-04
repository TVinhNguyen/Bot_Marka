"""News fixtures and a retrieval store for the offline Event Risk adapter.

News is stored as JSONL, one event per line. The
:class:`NewsStore.retrieve` method filters by symbol, recency, and
relevance so the adapter never sees future events (anti-leak) and
degrades predictably when the fixture is stale or empty.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

Impact = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class NewsEvent:
    """A single news item relevant to one or more Symbols."""

    event_id: str
    symbol: str
    scheduled_at: datetime
    impact: Impact
    title: str
    source: str = "fixture"
    relevance: float = 1.0  # 0..1
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.scheduled_at.tzinfo is None:
            raise ValueError("NewsEvent.scheduled_at must be timezone-aware (UTC)")
        if not 0.0 <= self.relevance <= 1.0:
            raise ValueError("relevance must be in [0, 1]")


def _parse_ts(raw: str) -> datetime:
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    ts = datetime.fromisoformat(raw)
    if ts.tzinfo is None:
        raise ValueError(f"news timestamp {raw!r} must be timezone-aware")
    return ts.astimezone(UTC)


class NewsStore:
    """JSONL-backed news store with time / symbol / recency retrieval."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._path.touch()

    @property
    def path(self) -> Path:
        return self._path

    def append(self, event: NewsEvent) -> None:
        payload = {
            "event_id": event.event_id,
            "symbol": event.symbol,
            "scheduled_at": event.scheduled_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "impact": event.impact,
            "title": event.title,
            "source": event.source,
            "relevance": event.relevance,
            "tags": list(event.tags),
        }
        with self._path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(payload, sort_keys=True) + "\n")
            fp.flush()
            os.fsync(fp.fileno())

    def load_all(self) -> list[NewsEvent]:
        out: list[NewsEvent] = []
        with self._path.open("r", encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                out.append(
                    NewsEvent(
                        event_id=str(rec["event_id"]),
                        symbol=str(rec["symbol"]),
                        scheduled_at=_parse_ts(str(rec["scheduled_at"])),
                        impact=rec.get("impact", "low"),
                        title=str(rec.get("title", "")),
                        source=str(rec.get("source", "fixture")),
                        relevance=float(rec.get("relevance", 1.0)),
                        tags=list(rec.get("tags", [])),
                    )
                )
        return out

    def retrieve(
        self,
        *,
        symbol: str,
        as_of: datetime,
        recency_window: timedelta = timedelta(hours=24),
        min_relevance: float = 0.0,
        include_future_within: timedelta = timedelta(hours=6),
    ) -> list[NewsEvent]:
        """Return news matching ``symbol`` and the time window around ``as_of``.

        * Past events must fall within ``[as_of - recency_window, as_of]``.
        * Future events (e.g. a scheduled central-bank release) are
          included if they fall within
          ``[as_of, as_of + include_future_within]``. This keeps the
          Event Risk adapter aware of upcoming landmines without leaking
          post-event price action.
        """
        earliest = as_of - recency_window
        latest = as_of + include_future_within
        out: list[NewsEvent] = []
        for event in self.load_all():
            if event.symbol != symbol:
                continue
            if event.relevance < min_relevance:
                continue
            if earliest <= event.scheduled_at <= latest:
                out.append(event)
        out.sort(key=lambda e: e.scheduled_at)
        return out
