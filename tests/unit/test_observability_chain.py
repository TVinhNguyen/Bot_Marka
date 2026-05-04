"""Audit hash chaining: tampering detection and append continuity."""

from __future__ import annotations

import json
from pathlib import Path

from ai_mt5.audit.trail import AuditRecord
from ai_mt5.observability.chain import (
    GENESIS_HASH,
    HashChainedAuditTrail,
    chain_records,
    verify_chain,
)


def _record(kind: str, trace: str, **payload: object) -> AuditRecord:
    return AuditRecord(
        kind=kind,
        trace_id=trace,
        timestamp="2026-04-01T00:00:00+00:00",
        payload=dict(payload),
    )


def test_chain_records_links_genesis_to_first() -> None:
    chained = chain_records([_record("tick.start", "t1"), _record("forecast", "t1", value=1.0)])
    assert chained[0]["prev_hash"] == GENESIS_HASH
    assert chained[1]["prev_hash"] == chained[0]["record_hash"]


def test_verify_clean_chain_passes() -> None:
    records = [
        _record("tick.start", "t1"),
        _record("forecast", "t1", value=1.0),
        _record("tick.success", "t1"),
    ]
    chained = chain_records(records)
    ok, error = verify_chain(chained)
    assert ok
    assert error is None


def test_tampering_detected_on_mid_chain_payload() -> None:
    chained = chain_records(
        [
            _record("tick.start", "t1"),
            _record("forecast", "t1", value=1.0),
            _record("tick.success", "t1"),
        ]
    )
    # Mutate the middle record's payload but leave the recorded hashes alone.
    chained[1]["payload"] = {"value": 99.0}
    ok, error = verify_chain(chained)
    assert not ok
    assert error is not None
    assert "link 1" in error


def test_chain_persists_across_reopen(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    trail_a = HashChainedAuditTrail(path)
    trail_a.append(_record("tick.start", "t1"))
    trail_a.append(_record("forecast", "t1", value=1.0))

    # Reopen and continue: the new trail must pick up the previous hash so
    # the chain is unbroken.
    trail_b = HashChainedAuditTrail(path)
    trail_b.append(_record("tick.success", "t1"))

    ok, error = trail_b.verify()
    assert ok, error


def test_verify_catches_swapped_records(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    trail = HashChainedAuditTrail(path)
    trail.append(_record("tick.start", "t1"))
    trail.append(_record("forecast", "t1", value=1.0))
    trail.append(_record("tick.success", "t1"))

    # Manually rewrite the file with the middle two records swapped.
    lines = path.read_text(encoding="utf-8").splitlines()
    swapped = "\n".join([lines[0], lines[2], lines[1]]) + "\n"
    path.write_text(swapped, encoding="utf-8")

    ok, _ = HashChainedAuditTrail(path).verify()
    assert not ok


def test_round_trip_json_safe(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    trail = HashChainedAuditTrail(path)
    trail.append(_record("tick.start", "t1"))
    raw = path.read_text(encoding="utf-8").splitlines()[0]
    obj = json.loads(raw)
    assert obj["prev_hash"] == GENESIS_HASH
    assert "record_hash" in obj
