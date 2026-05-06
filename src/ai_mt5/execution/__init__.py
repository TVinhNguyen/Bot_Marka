"""Execution and reconciliation primitives.

This package houses the local trade-intent log and the broker / local
state reconciler that issue #5 requires. It deliberately does **not**
implement ``order_send`` — the live executor will land in a follow-up
slice. What lives here today:

* :class:`LocalIntent` — the canonical record we keep about every trade
  the bot intends, has submitted, or believes is open.
* :class:`LocalIntentLog` — append-only JSONL ledger of intents so the
  reconciler can answer "what does the bot believe about the world?"
  even after a restart.
* :class:`Reconciler` — pure function comparing the intent log against
  broker positions (by ``magic`` + structured ``comment``) and
  classifying each side as matched, broker-only (unmanaged),
  local-only (orphaned), or timeout-pending (no auto-retry).
"""

from .intent import (
    LocalIntent,
    LocalIntentLog,
    LocalIntentLogProtocol,
    intent_id_from_trace,
    structured_comment,
)
from .reconcile import (
    BrokerPosition,
    ReconcileReport,
    reconcile,
)

__all__ = [
    "BrokerPosition",
    "LocalIntent",
    "LocalIntentLog",
    "LocalIntentLogProtocol",
    "ReconcileReport",
    "intent_id_from_trace",
    "reconcile",
    "structured_comment",
]
