"""Issue #1 + #2 end-to-end: load fixture, forecast, persist forecast and audit.

Verifies:

* a project entrypoint can run one dry_run tick locally,
* the tick creates a trace ID and propagates it into logs and audit,
* tick.start, forecast, meta_signal, risk_decision, tick.success records all
  share the same trace_id,
* a Baseline forecast is produced and queryable,
* the tick lands in HOLD when no broker snapshot is available,
* no Running Bar leaks into the pipeline.
"""

from __future__ import annotations

from pathlib import Path

from ai_mt5.audit import JsonlAuditTrail
from ai_mt5.data.forecast_store import JsonlForecastStore
from ai_mt5.tick import TickRunner


def test_dry_run_tick_records_full_pipeline(app_config, fixture_bars_path: Path) -> None:
    runner = TickRunner(app_config)
    result = runner.run(bar_fixture_path=fixture_bars_path)

    assert result.status == "success"
    assert result.forecast is not None
    assert result.risk_decision is not None
    assert not result.risk_decision.approved  # record-only HOLD path
    assert "dry_run_record_only" in result.risk_decision.rejected_by

    audit_path = Path(app_config.storage.audit_path) / "audit.jsonl"
    records = JsonlAuditTrail(audit_path).read_all()
    kinds = [r.kind for r in records]
    for required in ("tick.start", "forecast", "meta_signal", "risk_decision", "tick.success"):
        assert required in kinds, f"missing audit kind: {required}"
    # Every record in this run shares the same trace_id.
    assert {r.trace_id for r in records} == {result.trace_id}


def test_forecast_is_persisted_and_queryable(app_config, fixture_bars_path: Path) -> None:
    runner = TickRunner(app_config)
    runner.run(bar_fixture_path=fixture_bars_path)

    store = JsonlForecastStore(Path(app_config.storage.forecasts_path) / "forecasts.jsonl")
    rows = store.query(symbol="EURUSD", timeframe="M15")
    assert rows
    assert rows[-1]["model_name"] == "baseline_sma_momentum"


def test_failed_fixture_emits_tick_failure_audit(app_config, tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist.csv"
    runner = TickRunner(app_config)
    result = runner.run(bar_fixture_path=missing)

    assert result.status == "failure"
    audit_path = Path(app_config.storage.audit_path) / "audit.jsonl"
    records = JsonlAuditTrail(audit_path).read_all()
    kinds = [r.kind for r in records]
    assert "tick.start" in kinds
    assert "tick.failure" in kinds


def test_tick_refuses_running_bar_fixture(app_config, tmp_path: Path) -> None:
    bad = tmp_path / "bars.csv"
    bad.write_text(
        "open_time,open,high,low,close,volume,spread_points,is_closed\n"
        "2026-04-29T08:00:00+00:00,1.07,1.071,1.069,1.0705,1000,12,true\n"
        "2026-04-29T08:15:00+00:00,1.07,1.071,1.069,1.0705,1000,12,false\n",
        encoding="utf-8",
    )
    runner = TickRunner(app_config)
    result = runner.run(bar_fixture_path=bad)
    assert result.status == "failure"
    assert "Running Bar" in (result.error or "")


def test_full_pipeline_with_broker_snapshots_can_approve(
    app_config, fixture_bars_path: Path, account_snapshot, market_snapshot
) -> None:
    """When the operator supplies account+market snapshots, the Risk gate runs.

    Per ADR 0007, sizing scales by ``MetaSignal.confidence * agreement``.
    The Baseline's natural confidence on this short fixture is modest, so
    one of two outcomes is acceptable: (a) the gate approves at a *smaller*
    effective risk than ``base_risk_per_trade``, or (b) the floor falls
    below the broker's step granularity and the gate rejects with
    ``risk_below_min_cap``. Both outcomes are correct under the PRD.
    """
    runner = TickRunner(app_config)
    result = runner.run(
        bar_fixture_path=fixture_bars_path,
        account=account_snapshot,
        market=market_snapshot,
    )
    assert result.status == "success"
    assert result.forecast is not None
    if result.forecast.direction in ("BUY", "SELL"):
        assert result.risk_decision is not None
        if result.risk_decision.approved:
            assert result.risk_decision.side == result.forecast.direction
            assert "confidence=" in result.risk_decision.reason
            assert "effective_risk_pct=" in result.risk_decision.reason
        else:
            assert "risk_below_min_cap" in result.risk_decision.rejected_by


def test_dry_run_tick_can_replay_from_store(app_config, fixture_bars_path: Path) -> None:
    """Issue #6: dry-run-tick must replay from the local BarStore deterministically."""
    runner = TickRunner(app_config)
    seeded = runner.run(bar_fixture_path=fixture_bars_path, from_store=True)
    assert seeded.status == "success"

    replay = runner.run(from_store=True)
    assert replay.status == "success"
    assert replay.forecast is not None
    # Same fixture, same Closed Bars -> deterministic forecast direction.
    assert replay.forecast.direction == seeded.forecast.direction


def test_dry_run_tick_requires_source(app_config) -> None:
    runner = TickRunner(app_config)
    import pytest as _pytest

    with _pytest.raises(ValueError):
        runner.run()
