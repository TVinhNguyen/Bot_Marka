"""Agent narration schema + validation."""

from __future__ import annotations

import pytest

from ai_mt5.agent.narration import (
    AgentNarration,
    NarrationValidationError,
    narration_matches,
    validate_narration,
)


def _good_payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "trace_id": "trace-1",
        "direction": "BUY",
        "approved": True,
        "rationale": "agreement high, spread within limit",
        "rejection_reasons": [],
        "recommended_followups": [],
    }
    base.update(overrides)
    return base


def test_valid_payload_parses() -> None:
    out = validate_narration(_good_payload())
    assert isinstance(out, AgentNarration)
    assert out.direction == "BUY"


def test_unknown_direction_rejected() -> None:
    with pytest.raises(NarrationValidationError):
        validate_narration(_good_payload(direction="FLAT"))


def test_rationale_too_long_rejected() -> None:
    with pytest.raises(NarrationValidationError):
        validate_narration(_good_payload(rationale="x" * 401))


def test_rationale_with_executor_token_rejected() -> None:
    with pytest.raises(NarrationValidationError):
        validate_narration(_good_payload(rationale="please call order_send now"))


def test_rationale_with_credentials_rejected() -> None:
    with pytest.raises(NarrationValidationError):
        validate_narration(_good_payload(rationale="api_key sk-abc"))


def test_followups_with_forbidden_tokens_rejected() -> None:
    with pytest.raises(NarrationValidationError):
        validate_narration(_good_payload(recommended_followups=["set magic = 1234 to retry"]))


def test_missing_required_field_rejected() -> None:
    payload = _good_payload()
    payload.pop("trace_id")
    with pytest.raises(NarrationValidationError):
        validate_narration(payload)


def test_narration_matches_governance_check() -> None:
    nar = validate_narration(_good_payload())
    assert narration_matches(nar, direction="BUY", approved=True)
    assert not narration_matches(nar, direction="SELL", approved=True)
    assert not narration_matches(nar, direction="BUY", approved=False)
