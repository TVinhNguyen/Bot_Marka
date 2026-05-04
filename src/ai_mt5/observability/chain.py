"""Hash-chained audit trail.

Every record carries:

* ``prev_hash`` -- sha256 of the previous record (``"GENESIS"`` for the
  first), so any tampering anywhere in history is detectable by
  recomputing forward.
* ``record_hash`` -- sha256 of ``prev_hash || canonical_record_json``.

Verification is O(n): walk the file, recompute each hash, fail on the
first mismatch. The file format remains JSONL so the existing reader
keeps working; the new fields are extra payload keys.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ..audit.trail import AuditRecord

GENESIS_HASH = "GENESIS"


def _record_canonical(record: AuditRecord, prev_hash: str) -> str:
    """Stable JSON representation used as hash input."""
    payload = {
        "kind": record.kind,
        "trace_id": record.trace_id,
        "timestamp": record.timestamp,
        "schema_version": record.schema_version,
        "payload": record.payload,
        "prev_hash": prev_hash,
    }
    return json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def chain_records(records: list[AuditRecord]) -> list[dict[str, Any]]:
    """Return JSON-serialisable dicts with ``prev_hash`` + ``record_hash``."""
    out: list[dict[str, Any]] = []
    prev_hash = GENESIS_HASH
    for record in records:
        canonical = _record_canonical(record, prev_hash)
        record_hash = _hash(canonical)
        out.append(
            {
                **asdict(record),
                "prev_hash": prev_hash,
                "record_hash": record_hash,
            }
        )
        prev_hash = record_hash
    return out


def verify_chain(records: list[dict[str, Any]]) -> tuple[bool, str | None]:
    """Walk the chain and return ``(ok, error)``.

    ``ok=True`` means every link checks out. ``error`` is a short human
    description of the first mismatch (``"link <i>: prev_hash mismatch"``).
    """
    prev_hash = GENESIS_HASH
    for i, raw in enumerate(records):
        if raw.get("prev_hash") != prev_hash:
            return False, f"link {i}: prev_hash mismatch"
        record = AuditRecord(
            kind=raw["kind"],
            trace_id=raw["trace_id"],
            timestamp=raw["timestamp"],
            payload=raw.get("payload", {}),
            schema_version=raw.get("schema_version", 1),
        )
        expected = _hash(_record_canonical(record, prev_hash))
        if raw.get("record_hash") != expected:
            return False, f"link {i}: record_hash mismatch"
        prev_hash = raw["record_hash"]
    return True, None


class HashChainedAuditTrail:
    """JSONL audit trail variant that maintains a sha256 chain.

    Implements the same surface as :class:`ai_mt5.audit.trail.JsonlAuditTrail`
    so it satisfies the :class:`AuditTrail` Protocol; tests and callers swap
    via constructor injection.
    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._path.touch()
        self._prev_hash = self._recover_last_hash()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def last_hash(self) -> str:
        return self._prev_hash

    def append(self, record: AuditRecord) -> None:
        canonical = _record_canonical(record, self._prev_hash)
        record_hash = _hash(canonical)
        line = json.dumps(
            {
                **asdict(record),
                "prev_hash": self._prev_hash,
                "record_hash": record_hash,
            },
            sort_keys=True,
            default=str,
        )
        with self._path.open("a", encoding="utf-8") as fp:
            fp.write(line + "\n")
            fp.flush()
            os.fsync(fp.fileno())
        self._prev_hash = record_hash

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

    def read_chain(self) -> list[dict[str, Any]]:
        """Return the raw chained dicts (with ``prev_hash`` / ``record_hash``)."""
        if not self._path.exists():
            return []
        out: list[dict[str, Any]] = []
        with self._path.open("r", encoding="utf-8") as fp:
            for raw in fp:
                raw = raw.strip()
                if not raw:
                    continue
                out.append(json.loads(raw))
        return out

    def verify(self) -> tuple[bool, str | None]:
        return verify_chain(self.read_chain())

    # -- internals ---------------------------------------------------------

    def _recover_last_hash(self) -> str:
        """Pick up the chain head when re-opening an existing trail."""
        if not self._path.exists():
            return GENESIS_HASH
        last_hash = GENESIS_HASH
        with self._path.open("r", encoding="utf-8") as fp:
            for raw in fp:
                raw = raw.strip()
                if not raw:
                    continue
                obj = json.loads(raw)
                last_hash = obj.get("record_hash", last_hash)
        return last_hash
