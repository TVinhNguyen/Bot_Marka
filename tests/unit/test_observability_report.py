"""Daily/weekly operations report aggregator."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ai_mt5.audit.trail import AuditRecord
from ai_mt5.observability.report import build_period_report


def _record(kind: str, *, trace: str, ts: datetime, **payload: object) -> AuditRecord:
    return AuditRecord(
        kind=kind,
        trace_id=trace,
        timestamp=ts.isoformat(),
        payload=dict(payload),
    )


def _records() -> list[AuditRecord]:
    base = datetime(2026, 4, 1, 12, 0, tzinfo=UTC)
    return [
        _record("tick.start", trace="t1", ts=base),
        _record("forecast", trace="t1", ts=base, model="baseline"),
        _record("forecast", trace="t1", ts=base, model="kronos"),
        _record("meta_signal", trace="t1", ts=base, direction="BUY"),
        _record("risk_decision", trace="t1", ts=base, approved=True, rejected_by=[]),
        _record("tick.success", trace="t1", ts=base + timedelta(seconds=1)),
        _record("tick.start", trace="t2", ts=base + timedelta(minutes=1)),
        _record("forecast", trace="t2", ts=base + timedelta(minutes=1), model="baseline"),
        _record(
            "risk_decision",
            trace="t2",
            ts=base + timedelta(minutes=1),
            approved=False,
            rejected_by=["spread_too_wide", "low_agreement"],
        ),
        _record(
            "tick.failure",
            trace="t2",
            ts=base + timedelta(minutes=1, seconds=1),
            error="DataQualityError: too few bars",
        ),
        _record(
            "adapter_failure",
            trace="t2",
            ts=base + timedelta(minutes=1, seconds=1),
            adapter="kronos",
        ),
    ]


def test_report_aggregates_counts_correctly() -> None:
    records = _records()
    start = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
    end = datetime(2026, 4, 2, 0, 0, tzinfo=UTC)
    report = build_period_report(records, window_start=start, window_end=end)
    assert report.ticks_total == 2
    assert report.ticks_success == 1
    assert report.ticks_failed == 1
    assert report.forecasts_emitted == 3
    assert report.meta_signals == 1
    assert report.risk_decisions_approved == 1
    assert report.risk_decisions_rejected == 1
    assert report.distinct_traces == 2
    assert report.rejection_reasons == {"spread_too_wide": 1, "low_agreement": 1}
    assert report.adapter_failures == {"kronos": 1}
    assert report.error_kinds == {"DataQualityError": 1}


def test_report_excludes_records_outside_window() -> None:
    records = _records()
    # Tight window before any records exist.
    start = datetime(2026, 4, 1, 11, 59, 0, tzinfo=UTC)
    end = datetime(2026, 4, 1, 11, 59, 30, tzinfo=UTC)
    report = build_period_report(records, window_start=start, window_end=end)
    assert report.total_records == 0
    assert report.ticks_total == 0


def test_to_dict_round_trip_safe() -> None:
    records = _records()
    start = datetime(2026, 4, 1, tzinfo=UTC)
    end = datetime(2026, 4, 2, tzinfo=UTC)
    payload = build_period_report(records, window_start=start, window_end=end).to_dict()
    assert payload["ticks"]["total"] == 2
    assert payload["risk_decisions"]["approved"] == 1
    assert payload["window"]["start"].endswith("+00:00")


def test_to_markdown_renders_sections() -> None:
    records = _records()
    start = datetime(2026, 4, 1, tzinfo=UTC)
    end = datetime(2026, 4, 2, tzinfo=UTC)
    md = build_period_report(records, window_start=start, window_end=end).to_markdown()
    assert "# Operations report" in md
    assert "## Ticks" in md
    assert "## Top rejection reasons" in md
    assert "## Adapter failures" in md
    assert "## Error kinds" in md


def test_window_validation() -> None:
    with pytest.raises(ValueError):
        build_period_report(
            [],
            window_start=datetime(2026, 4, 2, tzinfo=UTC),
            window_end=datetime(2026, 4, 1, tzinfo=UTC),
        )
