"""Local trade-intent ledger.

Every trade the bot intends to send begins life here. The intent is
recorded **before** ``order_send`` is even attempted so that, if the
network call times out, the bot can still tell the operator "I tried
to open this trade but I never heard back" — that is the whole reason
issue #5 mandates a no-auto-retry policy on timeouts.

States (sticky, never auto-rollback):

* ``intended``  — emitted by the risk gate; not yet sent to broker.
* ``submitted`` — ``order_send`` returned a known ``ticket``.
* ``timeout``   — ``order_send`` did not return cleanly; we don't know
  whether the broker accepted it. Reconciliation must decide.
* ``closed``    — broker confirmed the position is closed (TP/SL/manual).
* ``orphaned``  — operator-marked: bot believes a trade should exist but
  the broker says it doesn't (and history lookup didn't find it either).

The ledger is JSONL on disk (one record per state change) so audit and
reconcile share one source of truth. New state events do not overwrite
old ones; reading reduces the per-``intent_id`` history into a current
view via ``LocalIntentLog.open_intents()``.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from ..utils.time_utils import to_iso, utcnow

IntentState = Literal["intended", "submitted", "timeout", "closed", "orphaned"]
Side = Literal["BUY", "SELL"]


@dataclass(frozen=True)
class LocalIntent:
    """The bot's belief about a single trade."""

    intent_id: str
    symbol: str
    side: Side
    volume: float
    magic: int
    comment: str
    state: IntentState
    ticket: int | None = None
    created_at: str = field(default_factory=lambda: to_iso(utcnow()))
    submitted_at: str | None = None
    last_seen_at: str | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, default=str)

    @classmethod
    def from_dict(cls, obj: dict[str, Any]) -> LocalIntent:
        return cls(
            intent_id=obj["intent_id"],
            symbol=obj["symbol"],
            side=obj["side"],
            volume=float(obj["volume"]),
            magic=int(obj["magic"]),
            comment=obj["comment"],
            state=obj["state"],
            ticket=int(obj["ticket"]) if obj.get("ticket") is not None else None,
            created_at=obj["created_at"],
            submitted_at=obj.get("submitted_at"),
            last_seen_at=obj.get("last_seen_at"),
        )


def intent_id_from_trace(trace_id: str, symbol: str, side: Side) -> str:
    """Deterministic intent_id derived from the originating tick.

    Using the trace_id keeps the intent linked to the audit record that
    spawned it and gives reconciliation a stable handle even after a
    crash between ``order_send`` and the audit write.
    """
    h = hashlib.sha256(f"{trace_id}|{symbol}|{side}".encode()).hexdigest()
    return h[:16]


def structured_comment(magic: int, intent_id: str, *, max_len: int = 31) -> str:
    """Build the broker comment string used for reconciliation.

    MT5 comments are capped at 31 characters. We pack ``magic`` and a
    short slice of the intent id so the broker's view of the trade can
    be linked back to the local intent purely by comparing comments —
    no shared database, no clock skew.
    """
    intent_short = intent_id[:8]
    candidate = f"{magic}:{intent_short}"
    if len(candidate) > max_len:
        # Fall back to the longest prefix that still fits; magic is
        # mandatory so we trim from the intent slice.
        head = f"{magic}:"
        tail_room = max_len - len(head)
        if tail_room <= 0:
            raise ValueError(f"magic {magic} is too long to fit in {max_len}-char broker comment")
        return head + intent_short[:tail_room]
    return candidate


@runtime_checkable
class LocalIntentLogProtocol(Protocol):
    """Contract any trade-intent ledger must satisfy."""

    def append(self, intent: LocalIntent) -> None: ...

    def open_intents(self) -> list[LocalIntent]: ...

    def all_intents(self) -> list[LocalIntent]: ...


class LocalIntentLog:
    """JSON-lines on-disk intent ledger.

    Each ``append`` writes one JSON record and fsyncs. Reads reduce the
    full history into the current state per ``intent_id`` (last write
    wins) so the reconciler always sees the most recent state without
    rewriting old records.
    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._path.touch()

    @property
    def path(self) -> Path:
        return self._path

    def append(self, intent: LocalIntent) -> None:
        line = intent.to_json()
        with self._path.open("a", encoding="utf-8") as fp:
            fp.write(line + "\n")
            fp.flush()
            os.fsync(fp.fileno())

    def all_intents(self) -> list[LocalIntent]:
        if not self._path.exists():
            return []
        out: list[LocalIntent] = []
        with self._path.open("r", encoding="utf-8") as fp:
            for raw in fp:
                raw = raw.strip()
                if not raw:
                    continue
                obj = json.loads(raw)
                out.append(LocalIntent.from_dict(obj))
        return out

    def open_intents(self) -> list[LocalIntent]:
        """Latest-state-per-intent_id where state is not ``closed``."""
        latest: dict[str, LocalIntent] = {}
        for record in self.all_intents():
            latest[record.intent_id] = record
        return [i for i in latest.values() if i.state != "closed"]


__all__ = [
    "IntentState",
    "LocalIntent",
    "LocalIntentLog",
    "LocalIntentLogProtocol",
    "Side",
    "intent_id_from_trace",
    "structured_comment",
]
