"""Issue #11 — Shadow Mode comparison report."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ai_mt5.domain.bar import Bar
from ai_mt5.runtime.shadow_report import ShadowReport, build_shadow_report


def _bar(t: datetime, close: float) -> Bar:
    return Bar(
        symbol="EURUSD",
        timeframe="M15",
        open_time=t,
        open=close,
        high=close + 0.0001,
        low=close - 0.0001,
        close=close,
        volume=100.0,
        spread_points=10,
    )


def _write_audit(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")


def _shadow_tick(trace_id: str, decision_time: datetime, direction: str) -> list[dict]:
    return [
        {
            "kind": "tick.start",
            "trace_id": trace_id,
            "payload": {
                "mode": "shadow",
                "symbol": "EURUSD",
                "timeframe": "M15",
                "fixture": "live",
            },
        },
        {
            "kind": "tick.success",
            "trace_id": trace_id,
            "payload": {
                "symbol": "EURUSD",
                "timeframe": "M15",
                "decision_time": decision_time.isoformat(),
                "forecast_direction": direction,
                "signal_direction": direction,
                "risk_approved": direction != "HOLD",
                "risk_rejected_by": [],
                "completed_at": decision_time.isoformat(),
            },
        },
    ]


def test_buy_decision_agrees_when_price_rises(tmp_path: Path) -> None:
    """A BUY decision must count as agreement when close rises by horizon."""
    audit = tmp_path / "audit.jsonl"
    t0 = datetime(2026, 4, 29, 12, 0, tzinfo=UTC)
    bars = [_bar(t0 + timedelta(minutes=15 * i), 1.0 + 0.0001 * i) for i in range(8)]
    _write_audit(audit, _shadow_tick("t1", bars[0].open_time, "BUY"))
    report = build_shadow_report(audit_path=audit, bars=bars, horizon_bars=4)
    assert report.n_decisions == 1
    assert report.n_directional == 1
    assert report.n_scored == 1
    assert report.n_agreed == 1
    assert report.accuracy == pytest.approx(1.0)


def test_sell_decision_disagrees_when_price_rises(tmp_path: Path) -> None:
    audit = tmp_path / "audit.jsonl"
    t0 = datetime(2026, 4, 29, 12, 0, tzinfo=UTC)
    bars = [_bar(t0 + timedelta(minutes=15 * i), 1.0 + 0.0001 * i) for i in range(8)]
    _write_audit(audit, _shadow_tick("t1", bars[0].open_time, "SELL"))
    report = build_shadow_report(audit_path=audit, bars=bars, horizon_bars=4)
    assert report.n_agreed == 0
    assert report.accuracy == pytest.approx(0.0)


def test_hold_decisions_excluded_from_accuracy(tmp_path: Path) -> None:
    """HOLDs must NOT inflate accuracy — they tell us nothing."""
    audit = tmp_path / "audit.jsonl"
    t0 = datetime(2026, 4, 29, 12, 0, tzinfo=UTC)
    bars = [_bar(t0 + timedelta(minutes=15 * i), 1.0 + 0.0001 * i) for i in range(8)]
    events = _shadow_tick("t1", bars[0].open_time, "HOLD") + _shadow_tick(
        "t2", bars[1].open_time, "BUY"
    )
    _write_audit(audit, events)
    report = build_shadow_report(audit_path=audit, bars=bars, horizon_bars=4)
    assert report.n_decisions == 2
    assert report.n_directional == 1  # only BUY counts
    assert report.n_scored == 1
    assert report.n_agreed == 1
    assert report.accuracy == pytest.approx(1.0)


def test_decision_with_insufficient_future_bars_is_unscored(tmp_path: Path) -> None:
    """A decision near the end of the bar series cannot be scored."""
    audit = tmp_path / "audit.jsonl"
    t0 = datetime(2026, 4, 29, 12, 0, tzinfo=UTC)
    bars = [_bar(t0 + timedelta(minutes=15 * i), 1.0 + 0.0001 * i) for i in range(5)]
    # Decision on bar[3], horizon=4 → would need bar[7] which doesn't exist.
    _write_audit(audit, _shadow_tick("t1", bars[3].open_time, "BUY"))
    report = build_shadow_report(audit_path=audit, bars=bars, horizon_bars=4)
    assert report.n_directional == 1
    assert report.n_scored == 0
    assert report.accuracy is None
    assert report.coverage == pytest.approx(0.0)


def test_non_shadow_modes_are_ignored(tmp_path: Path) -> None:
    """tick.start records with mode != shadow must NOT be reported."""
    audit = tmp_path / "audit.jsonl"
    t0 = datetime(2026, 4, 29, 12, 0, tzinfo=UTC)
    bars = [_bar(t0 + timedelta(minutes=15 * i), 1.0 + 0.0001 * i) for i in range(8)]
    events = _shadow_tick("t1", bars[0].open_time, "BUY")
    # Replace mode in tick.start to dry_run.
    events[0]["payload"]["mode"] = "dry_run"
    _write_audit(audit, events)
    report = build_shadow_report(audit_path=audit, bars=bars, horizon_bars=4)
    assert report.n_decisions == 0


def test_symbol_timeframe_filter(tmp_path: Path) -> None:
    audit = tmp_path / "audit.jsonl"
    t0 = datetime(2026, 4, 29, 12, 0, tzinfo=UTC)
    bars = [_bar(t0 + timedelta(minutes=15 * i), 1.0 + 0.0001 * i) for i in range(8)]
    events = _shadow_tick("t1", bars[0].open_time, "BUY")
    # Tag this tick as a different symbol.
    events[0]["payload"]["symbol"] = "GBPUSD"
    _write_audit(audit, events)
    report = build_shadow_report(audit_path=audit, bars=bars, horizon_bars=4, symbol="EURUSD")
    assert report.n_decisions == 0


def test_report_to_dict_is_json_safe(tmp_path: Path) -> None:
    audit = tmp_path / "audit.jsonl"
    t0 = datetime(2026, 4, 29, 12, 0, tzinfo=UTC)
    bars = [_bar(t0 + timedelta(minutes=15 * i), 1.0 + 0.0001 * i) for i in range(8)]
    _write_audit(audit, _shadow_tick("t1", bars[0].open_time, "BUY"))
    report = build_shadow_report(audit_path=audit, bars=bars, horizon_bars=4)
    payload = report.to_dict()
    json.dumps(payload, sort_keys=True)
    assert set(payload.keys()) >= {"horizon_bars", "n_scored", "accuracy", "outcomes"}
    assert isinstance(report, ShadowReport)


def test_invalid_horizon_raises() -> None:
    with pytest.raises(ValueError, match="horizon_bars"):
        build_shadow_report(audit_path=Path("/nonexistent"), bars=[], horizon_bars=0)
