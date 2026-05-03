"""Offline text-intelligence adapter (issue #8).

Ships a deterministic, prompt-injection-hardened Event Risk adapter
that scores recent news context. No external LLM is called here; the
adapter consumes fixture news items and produces a
Forecast-compatible output that the Ensemble can consume.
"""

from .event_risk import (
    EventRiskAdapter,
    EventRiskOutput,
    stale_event_risk,
)
from .guardrails import GuardrailError, sanitize_news_text, validate_event_risk
from .news import NewsEvent, NewsStore

__all__ = [
    "EventRiskAdapter",
    "EventRiskOutput",
    "GuardrailError",
    "NewsEvent",
    "NewsStore",
    "sanitize_news_text",
    "stale_event_risk",
    "validate_event_risk",
]
