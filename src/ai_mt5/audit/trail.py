"""Append-only Audit Trail.

The trail is the single source of truth for what the system observed and
decided. Every record carries:

* ``trace_id`` - links related entries within a tick (forecast, meta-signal,
  risk decision, executor result).
* ``kind`` - what kind of event the entry represents (``tick.start``,
  ``tick.success``, ``forecast``, ``risk_decision``, ...).
* ``payload`` - kind-specific structured data.

The default backend writes one JSON object per line (JSONL). Records are never
overwritten; corrections must be expressed as new records. The minimal
interface (:class:`AuditTrail`) is provided so future work can add database
backends or hash-chained governance without touching call sites.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from ..utils.time_utils import to_iso, utcnow


@dataclass(frozen=True)
class AuditRecord:
    """A single append-only audit entry."""

    kind: str
    trace_id: str
    timestamp: str = field(default_factory=lambda: to_iso(utcnow()))
    payload: dict[str, Any] = field(default_factory=dict)
    schema_version: int = 1

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, default=str)


@runtime_checkable
class AuditTrail(Protocol):
    """Append-only audit interface."""

    def append(self, record: AuditRecord) -> None: ...

    def read_all(self) -> list[AuditRecord]: ...


class JsonlAuditTrail:
    """JSON-lines on-disk audit trail. Each ``append`` is fsync-flushed."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Touch so subsequent reads don't error on a fresh trail.
        if not self._path.exists():
            self._path.touch()

    @property
    def path(self) -> Path:
        return self._path

    def append(self, record: AuditRecord) -> None:
        line = record.to_json()
        with self._path.open("a", encoding="utf-8") as fp:
            fp.write(line + "\n")
            fp.flush()
            os.fsync(fp.fileno())

    def read_all(self) -> list[AuditRecord]:
        if not self._path.exists():
            return []
        out: list[AuditRecord] = []
        with self._path.open("r", encoding="utf-8") as fp:
            for raw in fp:
                raw = raw.strip()
                if not raw:
                    continue
                obj = json.loads(raw)
                out.append(
                    AuditRecord(
                        kind=obj["kind"],
                        trace_id=obj["trace_id"],
                        timestamp=obj["timestamp"],
                        payload=obj.get("payload", {}),
                        schema_version=obj.get("schema_version", 1),
                    )
                )
        return out
