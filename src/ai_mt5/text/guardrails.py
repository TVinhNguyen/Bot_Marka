"""Guardrails for the offline Event Risk adapter.

Two jobs:

1. **Input sanitization** — strip any tokens from news titles that would
   let a malicious fixture tell an LLM (or a naive downstream) to send
   orders, mutate risk config, or override numerics.
2. **Output schema validation** — refuse any :class:`EventRiskOutput`
   whose fields are out of range, non-finite, or contain forbidden
   action tokens.

These gates make issue #8's guarantee concrete: prompt-injection
fixtures cannot cause order submission, risk mutation, or free-form
numeric overrides, and adapter outputs are schema-validated and
persisted with source metadata.
"""

from __future__ import annotations

import math
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .event_risk import EventRiskOutput


class GuardrailError(ValueError):
    """Raised when a news item or adapter output violates the guardrails."""


# Case-insensitive token list that must never round-trip to downstream
# components (execution, risk config, sizing).
FORBIDDEN_ACTION_TOKENS: tuple[str, ...] = (
    "order_send",
    "ordersend",
    "place order",
    "execute order",
    "set risk",
    "override risk",
    "max_risk",
    "base_risk",
    "bypass kill",
    "disable kill",
    "kill_switch=false",
    "magic=",
    "volume=",
    "sl=",
    "tp=",
)


_TOKEN_RE = re.compile(
    "|".join(re.escape(t) for t in FORBIDDEN_ACTION_TOKENS),
    re.IGNORECASE,
)


def sanitize_news_text(text: str) -> str:
    """Return ``text`` with forbidden action tokens redacted.

    The redaction happens on a copy; the original news item is left
    alone so audit trails record what the adapter actually saw.
    """
    return _TOKEN_RE.sub("[REDACTED]", text)


def contains_forbidden_tokens(text: str) -> bool:
    return bool(_TOKEN_RE.search(text))


def validate_event_risk(output: EventRiskOutput) -> None:
    """Raise :class:`GuardrailError` if ``output`` is not schema-valid."""
    if output.event_risk < 0.0 or output.event_risk > 1.0:
        raise GuardrailError(f"event_risk out of range: {output.event_risk}")
    if output.sentiment < -1.0 or output.sentiment > 1.0:
        raise GuardrailError(f"sentiment out of range: {output.sentiment}")
    if output.direction_bias not in {"BUY", "SELL", "HOLD"}:
        raise GuardrailError(f"direction_bias not allowed: {output.direction_bias!r}")
    if not isinstance(output.trade_permission, bool):
        raise GuardrailError("trade_permission must be a bool")
    if not math.isfinite(output.event_risk) or not math.isfinite(output.sentiment):
        raise GuardrailError("event_risk/sentiment must be finite")
    for key, value in output.metadata.items():
        if isinstance(value, str) and contains_forbidden_tokens(value):
            raise GuardrailError(f"metadata[{key!r}] contains forbidden action token")
