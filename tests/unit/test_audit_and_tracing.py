"""Issue #1: trace ID propagation and append-only audit trail."""

from __future__ import annotations

import json
from pathlib import Path

from ai_mt5.audit import AuditRecord, JsonlAuditTrail
from ai_mt5.utils.tracing import current_trace_id, new_trace_id, with_trace_id


def test_trace_id_is_unique_and_hex() -> None:
    a = new_trace_id()
    b = new_trace_id()
    assert a != b
    assert len(a) == 32
    int(a, 16)  # raises if not hex


def test_with_trace_id_propagates_via_contextvar() -> None:
    assert current_trace_id() is None
    with with_trace_id() as tid:
        assert current_trace_id() == tid
    assert current_trace_id() is None


def test_with_trace_id_nests() -> None:
    with with_trace_id("outer") as outer:
        assert current_trace_id() == outer
        with with_trace_id("inner") as inner:
            assert inner == "inner"
            assert current_trace_id() == "inner"
        assert current_trace_id() == "outer"


def test_jsonl_audit_trail_is_append_only(tmp_path: Path) -> None:
    trail = JsonlAuditTrail(tmp_path / "audit.jsonl")
    trail.append(AuditRecord(kind="tick.start", trace_id="t1", payload={"x": 1}))
    trail.append(AuditRecord(kind="tick.success", trace_id="t1", payload={"x": 2}))

    records = trail.read_all()
    assert [r.kind for r in records] == ["tick.start", "tick.success"]
    assert all(r.trace_id == "t1" for r in records)

    raw_lines = (tmp_path / "audit.jsonl").read_text().splitlines()
    assert len(raw_lines) == 2
    parsed = [json.loads(line) for line in raw_lines]
    assert parsed[0]["payload"] == {"x": 1}
    assert parsed[1]["payload"] == {"x": 2}


def test_audit_records_carry_iso_utc_timestamp(tmp_path: Path) -> None:
    trail = JsonlAuditTrail(tmp_path / "audit.jsonl")
    trail.append(AuditRecord(kind="tick.start", trace_id="abc", payload={}))
    rec = trail.read_all()[0]
    assert rec.timestamp.endswith("Z") or rec.timestamp.endswith("+00:00")
