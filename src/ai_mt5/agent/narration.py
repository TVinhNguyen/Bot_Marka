"""Schema-validated Audit Narration produced by the Agent Layer.

The narration is a *description* of what the deterministic pipeline
already decided, not a parallel decision. The agent fills it in after
the deterministic ``RiskDecision`` is final.

Schema validation here is strict: any narration that fails validation
triggers the deterministic fallback (see :class:`AgentLayer`).
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator

ALLOWED_DIRECTIONS = frozenset({"BUY", "SELL", "HOLD"})

_FORBIDDEN_TOKENS_RE = re.compile(
    r"(?:\border_send\b|\bmagic\s*=|\bvolume\s*=|\bkill_switch\s*=\s*false\b"
    r"|\bapi[_\- ]?key\b|\bpassword\b)",
    re.IGNORECASE,
)


class NarrationValidationError(ValueError):
    """Raised when an :class:`AgentNarration` fails schema or content checks."""


class AgentNarration(BaseModel):
    """Strict schema for the agent's free-form narration.

    Fields:
        direction: Mirrors the deterministic Meta-Signal direction; if the
            agent emits a different direction the layer falls back.
        approved: Mirrors ``RiskDecision.approved``.
        rationale: Short human description (<=400 chars). Must not contain
            executor or credential-shaped tokens.
        rejection_reasons: Echo of ``RiskDecision.rejected_by``.
        recommended_followups: Optional operator hints.
        trace_id: Pipeline trace_id this narration belongs to.
    """

    trace_id: str = Field(..., min_length=1, max_length=128)
    direction: str
    approved: bool
    rationale: str = Field(..., min_length=1, max_length=400)
    rejection_reasons: list[str] = Field(default_factory=list)
    recommended_followups: list[str] = Field(default_factory=list)

    @field_validator("direction")
    @classmethod
    def _check_direction(cls, value: str) -> str:
        if value not in ALLOWED_DIRECTIONS:
            raise ValueError(f"direction must be one of {sorted(ALLOWED_DIRECTIONS)}")
        return value

    @field_validator("rationale")
    @classmethod
    def _rationale_no_forbidden_tokens(cls, value: str) -> str:
        if _FORBIDDEN_TOKENS_RE.search(value):
            raise ValueError("rationale contains forbidden executor/credential tokens")
        return value

    @field_validator("recommended_followups")
    @classmethod
    def _followups_no_forbidden_tokens(cls, values: list[str]) -> list[str]:
        for entry in values:
            if _FORBIDDEN_TOKENS_RE.search(entry):
                raise ValueError(
                    "recommended_followups contains forbidden executor/credential tokens"
                )
        return values


def validate_narration(payload: dict[str, Any]) -> AgentNarration:
    """Parse + validate a narration payload.

    Wraps :class:`pydantic.ValidationError` so callers see the same
    domain error type regardless of validator implementation.
    """
    try:
        return AgentNarration.model_validate(payload)
    except ValidationError as exc:
        raise NarrationValidationError(str(exc)) from exc


def narration_matches(narration: AgentNarration, *, direction: str, approved: bool) -> bool:
    """Return True iff narration agrees with the deterministic outcome.

    The agent is allowed to elaborate (rationale, followups), but must
    not flip direction or approval status; this function is the
    governance check the layer uses before persisting.
    """
    return narration.direction == direction and narration.approved == approved
