"""Tests for the LocalIntentLog and intent helpers (issue #5)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ai_mt5.execution.intent import (
    LocalIntent,
    LocalIntentLog,
    intent_id_from_trace,
    structured_comment,
)


def test_intent_id_from_trace_is_deterministic() -> None:
    a = intent_id_from_trace("trace-abc", "EURUSD", "BUY")
    b = intent_id_from_trace("trace-abc", "EURUSD", "BUY")
    c = intent_id_from_trace("trace-abc", "EURUSD", "SELL")
    assert a == b
    assert a != c
    # Side-channel: stable length so the structured_comment fits.
    assert len(a) == 16


def test_structured_comment_packs_magic_and_intent() -> None:
    intent_id = intent_id_from_trace("trace", "EURUSD", "BUY")
    comment = structured_comment(magic=12345, intent_id=intent_id)
    assert comment.startswith("12345:")
    assert len(comment) <= 31


def test_structured_comment_truncates_to_max_len() -> None:
    """When the canonical intent slice does not fit, the helper trims
    the intent slice (never the magic) to stay under max_len."""
    intent_id = "0123456789abcdef" * 4
    comment = structured_comment(magic=12345, intent_id=intent_id, max_len=10)
    assert comment.startswith("12345:")
    assert len(comment) == 10


def test_structured_comment_rejects_unfittable_magic() -> None:
    with pytest.raises(ValueError, match="too long"):
        structured_comment(magic=12345678901234567890, intent_id="abc", max_len=10)


def test_local_intent_log_round_trip(tmp_path: Path) -> None:
    log = LocalIntentLog(tmp_path / "intents.jsonl")
    intent = LocalIntent(
        intent_id="abc",
        symbol="EURUSD",
        side="BUY",
        volume=0.01,
        magic=12345,
        comment="12345:abcdef",
        state="intended",
    )
    log.append(intent)
    loaded = log.all_intents()
    assert loaded == [intent]


def test_open_intents_returns_latest_state_per_intent(tmp_path: Path) -> None:
    """A trade that goes intended -> submitted -> closed must not be open."""
    log = LocalIntentLog(tmp_path / "intents.jsonl")
    base = dict(symbol="EURUSD", side="BUY", volume=0.01, magic=1, comment="1:x")

    log.append(LocalIntent(intent_id="a", state="intended", **base))  # type: ignore[arg-type]
    log.append(LocalIntent(intent_id="a", state="submitted", ticket=42, **base))  # type: ignore[arg-type]
    log.append(LocalIntent(intent_id="b", state="intended", **base))  # type: ignore[arg-type]
    log.append(LocalIntent(intent_id="a", state="closed", ticket=42, **base))  # type: ignore[arg-type]

    open_now = {i.intent_id: i.state for i in log.open_intents()}
    assert open_now == {"b": "intended"}


def test_local_intent_log_handles_missing_optional_fields(tmp_path: Path) -> None:
    """Older records may not carry submitted_at / last_seen_at."""
    path = tmp_path / "intents.jsonl"
    path.write_text(
        '{"intent_id":"x","symbol":"EURUSD","side":"BUY","volume":0.01,'
        '"magic":1,"comment":"1:x","state":"intended","ticket":null,'
        '"created_at":"2026-04-30T00:00:00+00:00"}\n'
    )
    log = LocalIntentLog(path)
    [intent] = log.all_intents()
    assert intent.intent_id == "x"
    assert intent.submitted_at is None
    assert intent.last_seen_at is None
