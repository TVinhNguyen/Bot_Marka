"""Deterministic offline Event Risk adapter.

Given a set of recent news events for a symbol, produce a structured
:class:`EventRiskOutput` the Ensemble can consume. The adapter:

* prefers **conservative** output when news is missing or stale,
* ignores any text that carries a forbidden action token (after
  sanitization, the offending event contributes zero sentiment),
* persists the resulting output with source metadata (event ids, window
  bounds, and an explicit reason).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from .guardrails import (
    GuardrailError,
    contains_forbidden_tokens,
    sanitize_news_text,
    validate_event_risk,
)
from .news import NewsEvent, NewsStore

Direction = Literal["BUY", "SELL", "HOLD"]

# Lightweight lexicon — good enough for fixture news in the offline slice.
_POSITIVE = {
    "beat",
    "beats",
    "rally",
    "rallies",
    "surge",
    "surges",
    "strong",
    "stronger",
    "upbeat",
    "bullish",
    "hawkish",
    "growth",
    "expansion",
}
_NEGATIVE = {
    "miss",
    "misses",
    "fall",
    "falls",
    "drop",
    "drops",
    "weak",
    "weaker",
    "bearish",
    "dovish",
    "recession",
    "crisis",
    "downgrade",
    "sanction",
    "sanctions",
}


@dataclass(frozen=True)
class EventRiskOutput:
    """Offline Event Risk forecast.

    ``event_risk`` is in ``[0, 1]`` — 0 = business as usual, 1 = do not
    trade. ``sentiment`` is in ``[-1, 1]``. ``direction_bias`` is the
    short-term preferred side if a trade is ever allowed.
    ``trade_permission`` is the final yes/no for the ensemble's
    hard-veto step; when ``False`` the Ensemble must HOLD.
    """

    symbol: str
    as_of: datetime
    event_risk: float
    sentiment: float
    direction_bias: Direction
    trade_permission: bool
    reason: str
    metadata: dict[str, object] = field(default_factory=dict)


def stale_event_risk(symbol: str, *, as_of: datetime, reason: str) -> EventRiskOutput:
    """Build a conservative output for stale or missing news."""
    return EventRiskOutput(
        symbol=symbol,
        as_of=as_of,
        event_risk=0.75,
        sentiment=0.0,
        direction_bias="HOLD",
        trade_permission=False,
        reason=reason,
        metadata={"mode": "stale_or_missing"},
    )


def _score_event(event: NewsEvent) -> tuple[float, float]:
    """Return ``(event_risk_contribution, sentiment_contribution)``.

    High-impact items contribute more event risk; sentiment comes from a
    simple lexicon over the sanitized title.
    """
    base_risk = {"low": 0.1, "medium": 0.4, "high": 0.8}.get(event.impact, 0.1)
    risk = base_risk * event.relevance

    title = sanitize_news_text(event.title).lower()
    if contains_forbidden_tokens(event.title):
        return risk, 0.0  # injection attempt: neutral sentiment contribution

    tokens = set(title.replace(".", " ").replace(",", " ").split())
    pos = len(tokens & _POSITIVE)
    neg = len(tokens & _NEGATIVE)
    sentiment = 0.0 if pos + neg == 0 else (pos - neg) / max(pos + neg, 1)
    return risk, sentiment * event.relevance


class EventRiskAdapter:
    """Offline Event Risk Model Adapter."""

    name = "event_risk"
    version = "offline-0.1.0"

    def __init__(
        self,
        store: NewsStore,
        *,
        recency_window: timedelta = timedelta(hours=24),
        include_future_within: timedelta = timedelta(hours=6),
        stale_after: timedelta = timedelta(days=7),
        high_risk_threshold: float = 0.6,
    ) -> None:
        self._store = store
        self._recency_window = recency_window
        self._include_future_within = include_future_within
        self._stale_after = stale_after
        self._high_risk_threshold = high_risk_threshold

    def evaluate(self, *, symbol: str, as_of: datetime) -> EventRiskOutput:
        """Return an :class:`EventRiskOutput` for ``symbol`` at ``as_of``."""
        events = self._store.retrieve(
            symbol=symbol,
            as_of=as_of,
            recency_window=self._recency_window,
            include_future_within=self._include_future_within,
        )
        # Gate 1: missing fixture entirely for this symbol.
        all_events = self._store.load_all()
        symbol_events = [e for e in all_events if e.symbol == symbol]
        if not symbol_events:
            return stale_event_risk(symbol, as_of=as_of, reason="no_news_for_symbol")
        # Gate 2: latest known news for this symbol is older than stale_after.
        latest = max(symbol_events, key=lambda e: e.scheduled_at)
        if as_of - latest.scheduled_at > self._stale_after and not events:
            return stale_event_risk(
                symbol,
                as_of=as_of,
                reason=f"stale_news_latest={latest.scheduled_at.isoformat()}",
            )
        # Gate 3: nothing in the relevant window.
        if not events:
            out = EventRiskOutput(
                symbol=symbol,
                as_of=as_of,
                event_risk=0.1,
                sentiment=0.0,
                direction_bias="HOLD",
                trade_permission=True,
                reason="no_news_in_window",
                metadata={"window_start": (as_of - self._recency_window).isoformat()},
            )
            validate_event_risk(out)
            return out

        risks: list[float] = []
        sentiments: list[float] = []
        used_ids: list[str] = []
        for event in events:
            risk, sentiment = _score_event(event)
            risks.append(risk)
            sentiments.append(sentiment)
            used_ids.append(event.event_id)

        event_risk = min(1.0, max(risks))
        sentiment = max(-1.0, min(1.0, sum(sentiments) / len(sentiments)))
        direction_bias: Direction
        if sentiment > 0.25:
            direction_bias = "BUY"
        elif sentiment < -0.25:
            direction_bias = "SELL"
        else:
            direction_bias = "HOLD"
        trade_permission = event_risk < self._high_risk_threshold
        out = EventRiskOutput(
            symbol=symbol,
            as_of=as_of,
            event_risk=event_risk,
            sentiment=sentiment,
            direction_bias=direction_bias,
            trade_permission=trade_permission,
            reason=f"n_events={len(events)} worst_risk={event_risk:.3f}",
            metadata={
                "events": used_ids,
                "window_start": (as_of - self._recency_window).isoformat(),
                "window_end": (as_of + self._include_future_within).isoformat(),
                "adapter_version": self.version,
            },
        )
        validate_event_risk(out)
        return out


class JsonlEventRiskStore:
    """Append-only persistence for Event Risk outputs (issue #8 AC)."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._path.touch()

    @property
    def path(self) -> Path:
        return self._path

    def append(self, output: EventRiskOutput) -> None:
        # Reject outputs with forbidden tokens in metadata before writing.
        validate_event_risk(output)
        payload = asdict(output)
        payload["as_of"] = output.as_of.isoformat()
        with self._path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(payload, sort_keys=True, default=str) + "\n")
            fp.flush()
            os.fsync(fp.fileno())


__all__ = [
    "EventRiskAdapter",
    "EventRiskOutput",
    "GuardrailError",
    "JsonlEventRiskStore",
    "stale_event_risk",
]
