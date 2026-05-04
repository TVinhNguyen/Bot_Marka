"""Issue #8: news retrieval by symbol, timestamp, recency."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ai_mt5.text.news import NewsEvent, NewsStore


def _evt(
    event_id: str,
    *,
    symbol: str,
    at: datetime,
    impact: str = "low",
    relevance: float = 1.0,
    title: str = "neutral headline",
) -> NewsEvent:
    return NewsEvent(
        event_id=event_id,
        symbol=symbol,
        scheduled_at=at,
        impact=impact,  # type: ignore[arg-type]
        title=title,
        relevance=relevance,
    )


def test_retrieve_filters_by_symbol_and_window(tmp_path: Path) -> None:
    store = NewsStore(tmp_path / "news.jsonl")
    now = datetime(2024, 6, 1, 12, 0, tzinfo=UTC)
    store.append(_evt("a", symbol="EURUSD", at=now - timedelta(hours=2)))
    store.append(_evt("b", symbol="GBPUSD", at=now - timedelta(hours=2)))
    store.append(_evt("c", symbol="EURUSD", at=now - timedelta(days=2)))

    hits = store.retrieve(symbol="EURUSD", as_of=now)
    assert [e.event_id for e in hits] == ["a"]


def test_retrieve_includes_near_future_but_not_far_future(tmp_path: Path) -> None:
    store = NewsStore(tmp_path / "news.jsonl")
    now = datetime(2024, 6, 1, 12, 0, tzinfo=UTC)
    store.append(_evt("near", symbol="EURUSD", at=now + timedelta(hours=3)))
    store.append(_evt("far", symbol="EURUSD", at=now + timedelta(days=2)))
    hits = store.retrieve(symbol="EURUSD", as_of=now)
    assert [e.event_id for e in hits] == ["near"]


def test_retrieve_sorted_by_scheduled_at(tmp_path: Path) -> None:
    store = NewsStore(tmp_path / "news.jsonl")
    now = datetime(2024, 6, 1, 12, 0, tzinfo=UTC)
    store.append(_evt("a2", symbol="EURUSD", at=now - timedelta(hours=1)))
    store.append(_evt("a1", symbol="EURUSD", at=now - timedelta(hours=5)))
    hits = store.retrieve(symbol="EURUSD", as_of=now)
    assert [e.event_id for e in hits] == ["a1", "a2"]


def test_news_event_rejects_naive_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        NewsEvent(
            event_id="x",
            symbol="EURUSD",
            scheduled_at=datetime(2024, 1, 1),
            impact="low",
            title="t",
        )


def test_retrieve_respects_min_relevance(tmp_path: Path) -> None:
    store = NewsStore(tmp_path / "news.jsonl")
    now = datetime(2024, 6, 1, 12, 0, tzinfo=UTC)
    store.append(_evt("lo", symbol="EURUSD", at=now - timedelta(hours=1), relevance=0.1))
    store.append(_evt("hi", symbol="EURUSD", at=now - timedelta(hours=1), relevance=0.9))
    hits = store.retrieve(symbol="EURUSD", as_of=now, min_relevance=0.5)
    assert [e.event_id for e in hits] == ["hi"]
