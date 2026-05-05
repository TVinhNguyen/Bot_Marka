"""Tests for the reconciler (issue #5).

Covers all four scenarios called out in the acceptance criteria:
clean match, broker-only position, local-only trade, and
timeout-before-persist.
"""

from __future__ import annotations

from ai_mt5.execution.intent import LocalIntent, intent_id_from_trace, structured_comment
from ai_mt5.execution.reconcile import BrokerPosition, reconcile

MAGIC = 12345


def _intent(
    *,
    trace: str = "trace-1",
    side: str = "BUY",
    state: str = "intended",
    ticket: int | None = None,
) -> LocalIntent:
    intent_id = intent_id_from_trace(trace, "EURUSD", side)  # type: ignore[arg-type]
    return LocalIntent(
        intent_id=intent_id,
        symbol="EURUSD",
        side=side,  # type: ignore[arg-type]
        volume=0.01,
        magic=MAGIC,
        comment=structured_comment(MAGIC, intent_id),
        state=state,  # type: ignore[arg-type]
        ticket=ticket,
    )


def _broker(
    *,
    intent: LocalIntent | None = None,
    ticket: int = 100,
    magic: int = MAGIC,
    comment: str | None = None,
    side: str = "BUY",
) -> BrokerPosition:
    return BrokerPosition(
        ticket=ticket,
        symbol="EURUSD",
        side=side,  # type: ignore[arg-type]
        volume=0.01,
        magic=magic,
        comment=comment if comment is not None else (intent.comment if intent else "12345:other"),
    )


def test_clean_match_reports_ok() -> None:
    intent = _intent()
    pos = _broker(intent=intent, ticket=100)
    report = reconcile(local_intents=[intent], broker_positions=[pos], magic=MAGIC)
    assert report.ok is True
    assert report.matched == ((intent, pos),)
    assert report.broker_only == ()
    assert report.local_only == ()
    assert report.timeout_pending == ()


def test_broker_only_position_is_unmanaged() -> None:
    """A broker position with our magic but no local intent → unmanaged."""
    pos = _broker(comment="12345:unknown")
    report = reconcile(local_intents=[], broker_positions=[pos], magic=MAGIC)
    assert report.ok is False
    assert report.matched == ()
    assert report.broker_only == (pos,)
    assert report.local_only == ()
    assert report.timeout_pending == ()


def test_local_only_intent_triggers_alert() -> None:
    """Bot believes a trade is open but the broker has no matching position."""
    intent = _intent(state="submitted", ticket=999)
    report = reconcile(local_intents=[intent], broker_positions=[], magic=MAGIC)
    assert report.ok is False
    assert report.local_only == (intent,)
    assert report.broker_only == ()
    assert report.timeout_pending == ()


def test_timeout_intent_with_matching_broker_pos_is_pending() -> None:
    """Issue #5: order_send timeout must NOT auto-retry. Even when the
    broker actually has the position, we surface it as timeout_pending
    so the operator decides — the reconciler never auto-promotes it
    to ``submitted``."""
    intent = _intent(state="timeout")
    pos = _broker(intent=intent, ticket=100)
    report = reconcile(local_intents=[intent], broker_positions=[pos], magic=MAGIC)
    assert report.ok is False
    # Critical: it is NOT in matched — operator must intervene.
    assert report.matched == ()
    assert report.timeout_pending == (intent,)
    assert report.local_only == ()
    assert report.broker_only == ()


def test_timeout_intent_without_broker_pos_stays_pending() -> None:
    """Timeout-before-persist with no broker echo: reconciler still
    flags it as timeout_pending so the operator can confirm orphan
    status — never auto-rolls back to ``intended`` or auto-retries."""
    intent = _intent(state="timeout")
    report = reconcile(local_intents=[intent], broker_positions=[], magic=MAGIC)
    assert report.timeout_pending == (intent,)
    assert report.local_only == ()


def test_foreign_magic_position_is_isolated() -> None:
    """Positions belonging to another bot / manual trader are isolated
    from the report so we never claim them as unmanaged."""
    foreign = _broker(magic=99999, comment="other-bot")
    intent = _intent()
    matched = _broker(intent=intent, ticket=100)
    report = reconcile(
        local_intents=[intent],
        broker_positions=[foreign, matched],
        magic=MAGIC,
    )
    assert report.ok is True
    assert report.foreign_positions == (foreign,)
    assert report.broker_only == ()


def test_ticket_mismatch_falls_back_to_local_only() -> None:
    """If a local intent already has a ticket but the broker comment
    matches a *different* ticket, refuse to silently rebind."""
    intent = _intent(state="submitted", ticket=111)
    pos = _broker(intent=intent, ticket=222)
    report = reconcile(local_intents=[intent], broker_positions=[pos], magic=MAGIC)
    assert report.ok is False
    assert report.local_only == (intent,)
    assert report.broker_only == (pos,)


def test_closed_intents_are_ignored() -> None:
    """A closed local intent must not appear in any bucket — it is
    settled history and the broker reflecting nothing for it is correct."""
    closed = _intent(state="closed")
    report = reconcile(local_intents=[closed], broker_positions=[], magic=MAGIC)
    assert report.ok is True
    assert report.local_only == ()


def test_broker_position_from_dict_normalises_side() -> None:
    pos = BrokerPosition.from_dict(
        {
            "ticket": 100,
            "symbol": "EURUSD",
            "type": 1,  # SELL
            "volume": 0.01,
            "magic": MAGIC,
            "comment": "12345:abc",
        }
    )
    assert pos.side == "SELL"


def test_report_to_dict_is_json_safe() -> None:
    intent = _intent()
    pos = _broker(intent=intent, ticket=100)
    foreign = _broker(magic=99999, comment="x")
    timeout = _intent(trace="t2", state="timeout")
    orphaned = _intent(trace="t3", state="submitted", ticket=999)
    extra_broker = _broker(comment="12345:nobody", ticket=200)

    report = reconcile(
        local_intents=[intent, timeout, orphaned],
        broker_positions=[pos, foreign, extra_broker],
        magic=MAGIC,
    )
    payload = report.to_dict()
    import json

    json.dumps(payload)  # round-trips
    assert payload["ok"] is False
    assert {p["ticket"] for p in payload["matched"]} == {100}
    assert {p["ticket"] for p in payload["broker_only"]} == {200}
    assert {i["intent_id"] for i in payload["timeout_pending"]} == {timeout.intent_id}
    assert {i["intent_id"] for i in payload["local_only"]} == {orphaned.intent_id}
