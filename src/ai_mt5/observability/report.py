"""Daily / weekly operations reports built from the persisted audit trail.

The report is consumed by:

* humans (Markdown) -- "what happened in the last 24h?";
* downstream automation (JSON) -- aggregator pipelines, dashboards.

The function intentionally only reads the audit trail; it does not look
at metric snapshots (which are in-process only and would be wiped on
restart).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from ..audit.trail import AuditRecord


@dataclass(frozen=True)
class OperationsReport:
    """Aggregated counters + samples for a window of audit entries."""

    window_start: datetime
    window_end: datetime
    total_records: int
    ticks_total: int
    ticks_success: int
    ticks_failed: int
    forecasts_emitted: int
    meta_signals: int
    risk_decisions_approved: int
    risk_decisions_rejected: int
    rejection_reasons: dict[str, int] = field(default_factory=dict)
    adapter_failures: dict[str, int] = field(default_factory=dict)
    error_kinds: dict[str, int] = field(default_factory=dict)
    distinct_traces: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "window": {
                "start": self.window_start.isoformat(),
                "end": self.window_end.isoformat(),
            },
            "total_records": self.total_records,
            "distinct_traces": self.distinct_traces,
            "ticks": {
                "total": self.ticks_total,
                "success": self.ticks_success,
                "failed": self.ticks_failed,
            },
            "forecasts_emitted": self.forecasts_emitted,
            "meta_signals": self.meta_signals,
            "risk_decisions": {
                "approved": self.risk_decisions_approved,
                "rejected": self.risk_decisions_rejected,
            },
            "rejection_reasons": dict(self.rejection_reasons),
            "adapter_failures": dict(self.adapter_failures),
            "error_kinds": dict(self.error_kinds),
        }

    def to_markdown(self) -> str:
        lines: list[str] = []
        lines.append(f"# Operations report ({self.window_start.date()} → {self.window_end.date()})")
        lines.append("")
        lines.append(
            f"- Window: `{self.window_start.isoformat()}` → `{self.window_end.isoformat()}`"
        )
        lines.append(f"- Total audit records: **{self.total_records}**")
        lines.append(f"- Distinct trace_ids: **{self.distinct_traces}**")
        lines.append("")
        lines.append("## Ticks")
        lines.append(f"- Total: **{self.ticks_total}**")
        lines.append(f"- Success: **{self.ticks_success}**")
        lines.append(f"- Failed: **{self.ticks_failed}**")
        lines.append("")
        lines.append("## Pipeline")
        lines.append(f"- Forecasts emitted: **{self.forecasts_emitted}**")
        lines.append(f"- Meta-Signals: **{self.meta_signals}**")
        lines.append(f"- Risk Decisions approved: **{self.risk_decisions_approved}**")
        lines.append(f"- Risk Decisions rejected: **{self.risk_decisions_rejected}**")
        if self.rejection_reasons:
            lines.append("")
            lines.append("## Top rejection reasons")
            for reason, count in sorted(
                self.rejection_reasons.items(), key=lambda kv: kv[1], reverse=True
            ):
                lines.append(f"- `{reason}`: {count}")
        if self.adapter_failures:
            lines.append("")
            lines.append("## Adapter failures")
            for adapter, count in sorted(
                self.adapter_failures.items(), key=lambda kv: kv[1], reverse=True
            ):
                lines.append(f"- `{adapter}`: {count}")
        if self.error_kinds:
            lines.append("")
            lines.append("## Error kinds")
            for kind, count in sorted(self.error_kinds.items(), key=lambda kv: kv[1], reverse=True):
                lines.append(f"- `{kind}`: {count}")
        return "\n".join(lines) + "\n"


def _record_in_window(record: AuditRecord, start: datetime, end: datetime) -> bool:
    try:
        ts = datetime.fromisoformat(record.timestamp)
    except ValueError:
        return False
    return start <= ts < end


def build_period_report(
    records: list[AuditRecord],
    *,
    window_start: datetime,
    window_end: datetime,
) -> OperationsReport:
    """Aggregate ``records`` into one :class:`OperationsReport`.

    Records outside ``[window_start, window_end)`` are ignored. The
    function never mutates inputs.
    """
    if window_end <= window_start:
        raise ValueError("window_end must be strictly after window_start")
    in_window = [r for r in records if _record_in_window(r, window_start, window_end)]

    rejection_reasons: Counter[str] = Counter()
    adapter_failures: Counter[str] = Counter()
    error_kinds: Counter[str] = Counter()

    ticks_success = 0
    ticks_failed = 0
    forecasts_emitted = 0
    meta_signals = 0
    risk_approved = 0
    risk_rejected = 0
    distinct_traces: set[str] = set()

    for record in in_window:
        distinct_traces.add(record.trace_id)
        if record.kind == "tick.success":
            ticks_success += 1
        elif record.kind == "tick.failure":
            ticks_failed += 1
            error = record.payload.get("error", "")
            kind = error.split(":", 1)[0] if isinstance(error, str) and error else "unknown"
            error_kinds[kind] += 1
        elif record.kind == "forecast":
            forecasts_emitted += 1
        elif record.kind == "meta_signal":
            meta_signals += 1
        elif record.kind == "risk_decision":
            if record.payload.get("approved"):
                risk_approved += 1
            else:
                risk_rejected += 1
                for reason in record.payload.get("rejected_by", []) or []:
                    rejection_reasons[str(reason)] += 1
        elif record.kind == "adapter_failure":
            name = str(record.payload.get("adapter", "unknown"))
            adapter_failures[name] += 1

    return OperationsReport(
        window_start=window_start,
        window_end=window_end,
        total_records=len(in_window),
        ticks_total=ticks_success + ticks_failed,
        ticks_success=ticks_success,
        ticks_failed=ticks_failed,
        forecasts_emitted=forecasts_emitted,
        meta_signals=meta_signals,
        risk_decisions_approved=risk_approved,
        risk_decisions_rejected=risk_rejected,
        rejection_reasons=dict(rejection_reasons),
        adapter_failures=dict(adapter_failures),
        error_kinds=dict(error_kinds),
        distinct_traces=len(distinct_traces),
    )


def default_window(*, now: datetime, days: int = 1) -> tuple[datetime, datetime]:
    """Return ``(start, end)`` for "the last N days, aligned to midnight UTC"."""
    end = now
    start = now - timedelta(days=days)
    return start, end
