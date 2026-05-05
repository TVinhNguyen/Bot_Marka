"""Issue #5 — broker / local trade-state reconciliation.

The reconciler is a **pure function** over two snapshots:

1. The local :class:`LocalIntent` log (what the bot believes is open).
2. The broker's open positions for our ``magic`` (what is actually open).

It produces a :class:`ReconcileReport` with four buckets:

* ``matched`` — local + broker agree (state may need promotion to
  ``submitted`` if a timeout intent's twin is sitting on the broker).
* ``broker_only`` — broker has a position with our ``magic`` that the
  bot does not know about. **Unmanaged** in the issue's language; the
  operator decides whether to attach or close.
* ``local_only`` — bot believes the trade is open but the broker does
  not. Triggers a history lookup or operator alert.
* ``timeout_pending`` — local intent state is ``timeout`` and **does**
  match a broker position. The bot must NOT auto-retry order_send (that
  is an explicit acceptance criterion of issue #5); the operator decides
  whether to promote the intent to ``submitted`` or treat it as orphan.

The reconciler does not mutate state and does not call the broker. Live
adapters live one layer up (CLI / TickRunner) and are responsible for
fetching the broker positions and writing the resulting report into the
audit trail.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .intent import LocalIntent, Side


@dataclass(frozen=True)
class BrokerPosition:
    """Broker-side position normalised for reconciliation.

    Constructed from ``MT5Client.positions()`` rows on the live path or
    from fixtures in tests. All comparisons are by ``magic`` and
    ``comment`` plus the broker-assigned ``ticket``.
    """

    ticket: int
    symbol: str
    side: Side
    volume: float
    magic: int
    comment: str

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> BrokerPosition:
        type_value = row.get("type")
        # MT5: 0 = BUY, 1 = SELL. Strings allowed for tests / future API.
        if isinstance(type_value, str):
            side: Side = "SELL" if type_value.upper().endswith("SELL") else "BUY"
        else:
            side = "SELL" if int(type_value or 0) == 1 else "BUY"
        return cls(
            ticket=int(row["ticket"]),
            symbol=str(row["symbol"]),
            side=side,
            volume=float(row.get("volume", 0.0)),
            magic=int(row.get("magic", 0)),
            comment=str(row.get("comment", "")),
        )


@dataclass(frozen=True)
class ReconcileReport:
    """Outcome of one reconciliation pass."""

    matched: tuple[tuple[LocalIntent, BrokerPosition], ...] = field(default_factory=tuple)
    broker_only: tuple[BrokerPosition, ...] = field(default_factory=tuple)
    local_only: tuple[LocalIntent, ...] = field(default_factory=tuple)
    timeout_pending: tuple[LocalIntent, ...] = field(default_factory=tuple)
    foreign_positions: tuple[BrokerPosition, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return not (self.broker_only or self.local_only or self.timeout_pending)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "matched": [
                {
                    "intent_id": intent.intent_id,
                    "ticket": pos.ticket,
                    "symbol": intent.symbol,
                    "side": intent.side,
                    "volume": intent.volume,
                    "intent_state": intent.state,
                }
                for intent, pos in self.matched
            ],
            "broker_only": [
                {
                    "ticket": p.ticket,
                    "symbol": p.symbol,
                    "side": p.side,
                    "volume": p.volume,
                    "comment": p.comment,
                }
                for p in self.broker_only
            ],
            "local_only": [
                {
                    "intent_id": i.intent_id,
                    "symbol": i.symbol,
                    "side": i.side,
                    "volume": i.volume,
                    "state": i.state,
                    "comment": i.comment,
                }
                for i in self.local_only
            ],
            "timeout_pending": [
                {
                    "intent_id": i.intent_id,
                    "symbol": i.symbol,
                    "side": i.side,
                    "volume": i.volume,
                    "comment": i.comment,
                }
                for i in self.timeout_pending
            ],
            "foreign_positions": [
                {
                    "ticket": p.ticket,
                    "symbol": p.symbol,
                    "side": p.side,
                    "volume": p.volume,
                    "magic": p.magic,
                    "comment": p.comment,
                }
                for p in self.foreign_positions
            ],
        }


def _match_key(intent: LocalIntent) -> tuple[int, str]:
    return (intent.magic, intent.comment)


def _broker_key(pos: BrokerPosition) -> tuple[int, str]:
    return (pos.magic, pos.comment)


def reconcile(
    *,
    local_intents: list[LocalIntent],
    broker_positions: list[BrokerPosition],
    magic: int,
) -> ReconcileReport:
    """Compare local intents against broker positions for our ``magic``.

    Pure function. Inputs are snapshots; outputs are tuples of references
    into those snapshots. Caller is responsible for persisting the result
    into the audit trail and / or alerting the operator.
    """
    foreign: list[BrokerPosition] = [p for p in broker_positions if p.magic != magic]
    ours: list[BrokerPosition] = [p for p in broker_positions if p.magic == magic]
    open_locals: list[LocalIntent] = [
        i for i in local_intents if i.state in ("intended", "submitted", "timeout")
    ]

    by_local: dict[tuple[int, str], LocalIntent] = {_match_key(i): i for i in open_locals}
    by_broker: dict[tuple[int, str], BrokerPosition] = {_broker_key(p): p for p in ours}

    matched: list[tuple[LocalIntent, BrokerPosition]] = []
    timeout_pending: list[LocalIntent] = []
    matched_keys: set[tuple[int, str]] = set()

    # Match by (magic, comment). Ticket-based match is layered on top:
    # if a local intent already has a ticket, it must agree with the
    # broker side.
    for key, intent in by_local.items():
        broker = by_broker.get(key)
        if broker is None:
            continue
        if intent.ticket is not None and intent.ticket != broker.ticket:
            # Comment matches but ticket disagrees → treat as
            # local-only so the operator can decide rather than
            # silently rebinding the intent to a different ticket.
            continue
        matched_keys.add(key)
        if intent.state == "timeout":
            timeout_pending.append(intent)
        else:
            matched.append((intent, broker))

    broker_only = tuple(p for k, p in by_broker.items() if k not in matched_keys)
    local_only = tuple(
        i for k, i in by_local.items() if k not in matched_keys and i.state != "timeout"
    )
    timeout_only = tuple(
        i for k, i in by_local.items() if k not in matched_keys and i.state == "timeout"
    )
    # Timeouts that did not match a broker position are still
    # timeout_pending — the operator must decide. Importantly, the
    # reconciler never auto-promotes them to submitted (issue #5).
    timeout_pending = list(timeout_pending) + list(timeout_only)

    return ReconcileReport(
        matched=tuple(matched),
        broker_only=broker_only,
        local_only=local_only,
        timeout_pending=tuple(timeout_pending),
        foreign_positions=tuple(foreign),
    )


__all__ = ["BrokerPosition", "ReconcileReport", "reconcile"]
