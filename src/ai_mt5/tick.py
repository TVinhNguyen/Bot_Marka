"""Single dry_run tick orchestrator.

Wires together:

* config -> validated AppConfig
* trace ID -> log + audit context
* Closed Bar fixture -> anti-leak features -> Baseline Forecast
* Forecast -> Meta-Signal -> Risk Decision (HOLD path in this slice)
* every step persisted to the Audit Trail.

A "tick" is a single end-to-end pipeline run for one symbol-timeframe. In
``dry_run`` mode the tick must never call ``order_send``; this module enforces
that by simply not importing any executor code.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .audit import AuditRecord, AuditTrail, JsonlAuditTrail
from .baseline import BaselineAdapter
from .config.models import AppConfig, SymbolTimeframe
from .data import (
    BarStore,
    FreshnessState,
    FreshnessStatus,
    build_features,
    ingest_bars,
    load_closed_bars_csv,
)
from .data.forecast_store import JsonlForecastStore
from .data.quality import QualityConfig, QualityReport
from .domain.bar import Bar
from .domain.forecast import Forecast, MetaSignal
from .domain.market import AccountSnapshot, MarketSnapshot
from .domain.risk import RiskDecision
from .risk import RiskManager
from .risk.kill_switch import FileKillSwitch, KillSwitch
from .utils.logging_setup import get_logger
from .utils.time_utils import to_iso, utcnow
from .utils.tracing import with_trace_id


class DataQualityError(RuntimeError):
    """Raised when a blocking market-data quality issue prevents a tick.

    Core bar data failure blocks trading (per issue #6); optional checks
    degrade to warnings only.
    """

    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons) or "unknown data quality failure")
        self.reasons = reasons


@dataclass(frozen=True)
class TickResult:
    """Outcome of a single tick."""

    trace_id: str
    symbol: str
    timeframe: str
    decision_time: str
    forecast: Forecast | None
    risk_decision: RiskDecision | None
    status: str  # "success" | "failure" | "no_data"
    error: str | None = None
    data_freshness: FreshnessStatus | None = None
    data_quality: QualityReport | None = None


class TickRunner:
    """Run one dry_run tick and write Audit Trail records for it."""

    def __init__(
        self,
        config: AppConfig,
        *,
        audit: AuditTrail | None = None,
        forecast_store: JsonlForecastStore | None = None,
        kill_switch: KillSwitch | None = None,
        baseline: BaselineAdapter | None = None,
        bar_store: BarStore | None = None,
    ) -> None:
        self._cfg = config
        self._audit = audit or JsonlAuditTrail(Path(config.storage.audit_path) / "audit.jsonl")
        self._forecast_store = forecast_store or JsonlForecastStore(
            Path(config.storage.forecasts_path) / "forecasts.jsonl"
        )
        self._kill = kill_switch or FileKillSwitch(config.risk.kill_switch_file)
        self._baseline = baseline or BaselineAdapter()
        self._bar_store = bar_store or BarStore(config.storage.bars_path)
        self._risk = RiskManager(
            config.risk,
            self._kill,
            magic=config.execution.magic,
            order_comment=config.execution.order_comment,
        )
        self._log = get_logger("ai_mt5.tick")

    # -- data-health helpers -------------------------------------------------

    def _quality_config(self) -> QualityConfig:
        dq = self._cfg.data_quality
        return QualityConfig(
            return_outlier_mad_multiple=dq.return_outlier_mad_multiple,
            return_outlier_min_samples=dq.return_outlier_min_samples,
            gap_tolerance=dq.gap_tolerance,
            spread_max_points=dict(dq.spread_max_points),
        )

    def ingest(self, bars: list[Bar]) -> QualityReport:
        """Run quality gates and persist bars through :class:`BarStore`.

        Intended for smoke tests and fixture replay; production ingest will
        use an MT5-backed source.
        """
        if not bars:
            raise ValueError("ingest requires at least one Bar")
        result = ingest_bars(
            bars,
            store=self._bar_store,
            symbol=bars[0].symbol,
            timeframe=bars[0].timeframe,
            config=self._quality_config(),
        )
        return result.report

    def freshness(self, *, now: datetime | None = None) -> FreshnessStatus:
        """Return freshness of the primary symbol-timeframe."""
        ref = now or utcnow()
        sym = self._cfg.primary_symbol()
        dq = self._cfg.data_quality
        return self._bar_store.freshness(
            symbol=sym.symbol,
            timeframe=sym.timeframe,
            now=ref,
            stale_after_bars=dq.stale_after_bars,
            expired_after_bars=dq.expired_after_bars,
        )

    # -- public --------------------------------------------------------------

    def run(
        self,
        *,
        bar_fixture_path: str | Path | None = None,
        from_store: bool = False,
        account: AccountSnapshot | None = None,
        market: MarketSnapshot | None = None,
        now: datetime | None = None,
    ) -> TickResult:
        """Run one dry_run tick.

        Bars come from one of two sources:

        * ``bar_fixture_path`` (CSV) -- the original smoke-test path.
        * ``from_store=True`` -- deterministic replay from the local
          :class:`BarStore`, which is the source of truth for production.
          ``bar_fixture_path`` is then optional; if both are provided, the
          fixture is ingested into the store first (idempotent) so a single
          command can seed-and-replay.

        ``account`` and ``market`` snapshots may be supplied by tests or the
        baseline-tick fixture path. When omitted, this slice short-circuits
        the Risk gate: the forecast is still recorded and audited but the
        tick ends in HOLD.
        """
        if not from_store and bar_fixture_path is None:
            raise ValueError("run() requires either bar_fixture_path or from_store=True")
        symbol = self._cfg.primary_symbol()
        source: str
        with with_trace_id() as trace_id:
            try:
                if from_store and bar_fixture_path is not None:
                    seed = load_closed_bars_csv(
                        bar_fixture_path,
                        symbol=symbol.symbol,
                        timeframe=symbol.timeframe,
                    )
                    seed_report = self.ingest(seed)
                    if not seed_report.ok:
                        # Fail loud rather than silently replay whatever the
                        # store already had: the operator asked us to use this
                        # fixture and its quality gates blocked the write.
                        raise DataQualityError(
                            [
                                f"seed ingest blocked: {issue.message}"
                                for issue in seed_report.blocking_issues
                            ]
                        )
                if from_store:
                    source = f"store:{self._bar_store.path_for(symbol.symbol, symbol.timeframe)}"
                else:
                    assert bar_fixture_path is not None
                    source = str(bar_fixture_path)
                self._audit_tick_start(trace_id, symbol, source)
                self._log.info(
                    "tick.start",
                    symbol=symbol.symbol,
                    timeframe=symbol.timeframe,
                    fixture=source,
                    mode=self._cfg.environment.mode,
                )

                if from_store:
                    bars = self._bar_store.load(symbol=symbol.symbol, timeframe=symbol.timeframe)
                else:
                    assert bar_fixture_path is not None
                    bars = load_closed_bars_csv(
                        bar_fixture_path,
                        symbol=symbol.symbol,
                        timeframe=symbol.timeframe,
                    )
                if len(bars) < 2:
                    raise ValueError("tick requires at least 2 Closed Bars (history + decision)")

                data_quality = self._run_quality_gates(bars, symbol)
                self._audit_data_quality(trace_id, data_quality)
                if not data_quality.ok:
                    raise DataQualityError(
                        [issue.message for issue in data_quality.blocking_issues]
                    )

                # When replaying from the store, ``bars[-1].open_time`` IS the
                # store's latest bar, so using it as ``now`` would always yield
                # ``lag=0`` and ``FreshnessState.FRESH`` -- defeating the
                # ``block_tick_on_expired`` guard. Default to wall-clock time
                # for from_store, while letting callers pin ``now`` for
                # deterministic tests.
                if from_store:
                    freshness_now = now or utcnow()
                else:
                    freshness_now = bars[-1].open_time
                freshness = self._bar_store.freshness(
                    symbol=symbol.symbol,
                    timeframe=symbol.timeframe,
                    now=freshness_now,
                    stale_after_bars=self._cfg.data_quality.stale_after_bars,
                    expired_after_bars=self._cfg.data_quality.expired_after_bars,
                )
                self._audit_freshness(trace_id, freshness)
                # Only block on store freshness when the tick is actually
                # replaying from the store. In the CSV-fixture path the bars
                # are authoritative and the local store may legitimately be
                # empty or out of date; we still emit the freshness audit
                # record above for visibility.
                if (
                    from_store
                    and self._cfg.data_quality.block_tick_on_expired
                    and freshness.state is FreshnessState.EXPIRED
                ):
                    raise DataQualityError(
                        [
                            f"data store freshness={freshness.state.value} "
                            f"(lag_bars={freshness.lag_bars:.2f})"
                        ]
                    )

                history = bars[:-1]
                decision_bar = bars[-1]
                features = build_features(history, decision_bar)
                forecast = self._baseline.forecast(
                    features, symbol=symbol.symbol, timeframe=symbol.timeframe
                )
                self._forecast_store.append(forecast)
                self._audit_forecast(trace_id, forecast)

                # In this slice the ensemble degenerates to one model; we wrap
                # the Baseline Forecast in a single-component MetaSignal so
                # downstream risk logic uses the same contract it will use in
                # production.
                signal = self._wrap_meta_signal(forecast)
                self._audit_meta_signal(trace_id, signal)

                if account is not None and market is not None:
                    decision = self._risk.evaluate(
                        signal, account, market, now=decision_bar.open_time
                    )
                else:
                    decision = self._record_only_hold(signal)
                self._audit_risk_decision(trace_id, decision, signal)

                self._audit_tick_success(trace_id, symbol, decision_bar, forecast, decision)
                self._log.info(
                    "tick.success",
                    direction=signal.direction,
                    approved=decision.approved,
                    rejected_by=decision.rejected_by,
                )
                return TickResult(
                    trace_id=trace_id,
                    symbol=symbol.symbol,
                    timeframe=symbol.timeframe,
                    decision_time=to_iso(decision_bar.open_time),
                    forecast=forecast,
                    risk_decision=decision,
                    status="success",
                    data_freshness=freshness,
                    data_quality=data_quality,
                )

            except Exception as exc:
                self._audit_tick_failure(trace_id, symbol, repr(exc))
                self._log.error(
                    "tick.failure",
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                return TickResult(
                    trace_id=trace_id,
                    symbol=symbol.symbol,
                    timeframe=symbol.timeframe,
                    decision_time="",
                    forecast=None,
                    risk_decision=None,
                    status="failure",
                    error=f"{type(exc).__name__}: {exc}",
                )

    # -- helpers -------------------------------------------------------------

    def _run_quality_gates(self, bars: list[Bar], symbol: SymbolTimeframe) -> QualityReport:
        from .data.quality import run_quality_gates as _run

        return _run(
            bars,
            symbol=symbol.symbol,
            timeframe=symbol.timeframe,
            config=self._quality_config(),
        )

    def _wrap_meta_signal(self, forecast: Forecast) -> MetaSignal:
        return MetaSignal(
            direction=forecast.direction,
            final_score=forecast.score,
            raw_score=forecast.raw_score,
            agreement=1.0,  # only one model active in this slice
            confidence=forecast.confidence,
            cost_penalty=0.0,
            uncertainty_penalty=forecast.uncertainty,
            event_penalty=0.0,
            veto_reasons=[],
            reason=forecast.reason,
            components={forecast.model_name: forecast},
            timestamp=forecast.timestamp,
        )

    def _record_only_hold(self, signal: MetaSignal) -> RiskDecision:
        return RiskDecision.reject(
            ["dry_run_record_only"],
            magic=self._cfg.execution.magic,
            comment=self._cfg.execution.order_comment,
            reason=f"signal={signal.direction} -> record-only HOLD",
        )

    # -- audit emitters ------------------------------------------------------

    def _audit_tick_start(
        self, trace_id: str, symbol: SymbolTimeframe, fixture: str | Path
    ) -> None:
        self._audit.append(
            AuditRecord(
                kind="tick.start",
                trace_id=trace_id,
                payload={
                    "mode": self._cfg.environment.mode,
                    "symbol": symbol.symbol,
                    "timeframe": symbol.timeframe,
                    "fixture": str(fixture),
                },
            )
        )

    def _audit_forecast(self, trace_id: str, forecast: Forecast) -> None:
        self._audit.append(
            AuditRecord(
                kind="forecast",
                trace_id=trace_id,
                payload={
                    "model_name": forecast.model_name,
                    "symbol": forecast.symbol,
                    "timeframe": forecast.timeframe,
                    "direction": forecast.direction,
                    "score": forecast.score,
                    "confidence": forecast.confidence,
                    "uncertainty": forecast.uncertainty,
                    "expected_return": forecast.expected_return,
                    "horizon": forecast.horizon,
                    "reason": forecast.reason,
                },
            )
        )

    def _audit_meta_signal(self, trace_id: str, signal: MetaSignal) -> None:
        self._audit.append(
            AuditRecord(
                kind="meta_signal",
                trace_id=trace_id,
                payload={
                    "direction": signal.direction,
                    "final_score": signal.final_score,
                    "agreement": signal.agreement,
                    "confidence": signal.confidence,
                    "veto_reasons": signal.veto_reasons,
                    "components": list(signal.components.keys()),
                },
            )
        )

    def _audit_risk_decision(
        self, trace_id: str, decision: RiskDecision, signal: MetaSignal
    ) -> None:
        self._audit.append(
            AuditRecord(
                kind="risk_decision",
                trace_id=trace_id,
                payload={
                    "approved": decision.approved,
                    "side": decision.side,
                    "volume": decision.volume,
                    "sl": decision.sl,
                    "tp": decision.tp,
                    "magic": decision.magic,
                    "comment": decision.comment,
                    "reason": decision.reason,
                    "rejected_by": decision.rejected_by,
                    "signal_direction": signal.direction,
                },
            )
        )

    def _audit_tick_success(
        self,
        trace_id: str,
        symbol: SymbolTimeframe,
        decision_bar: Bar,
        forecast: Forecast,
        decision: RiskDecision,
    ) -> None:
        self._audit.append(
            AuditRecord(
                kind="tick.success",
                trace_id=trace_id,
                payload={
                    "symbol": symbol.symbol,
                    "timeframe": symbol.timeframe,
                    "decision_time": to_iso(decision_bar.open_time),
                    "forecast_direction": forecast.direction,
                    "risk_approved": decision.approved,
                    "risk_rejected_by": decision.rejected_by,
                    "completed_at": to_iso(utcnow()),
                },
            )
        )

    def _audit_data_quality(self, trace_id: str, report: QualityReport) -> None:
        self._audit.append(
            AuditRecord(
                kind="data_quality",
                trace_id=trace_id,
                payload={
                    "symbol": report.symbol,
                    "timeframe": report.timeframe,
                    "n_bars": report.n_bars,
                    "ok": report.ok,
                    "blocking": [
                        {"code": i.code, "message": i.message} for i in report.blocking_issues
                    ],
                    "warnings": [{"code": i.code, "message": i.message} for i in report.warnings],
                },
            )
        )

    def _audit_freshness(self, trace_id: str, freshness: FreshnessStatus) -> None:
        self._audit.append(
            AuditRecord(
                kind="data_freshness",
                trace_id=trace_id,
                payload={
                    "symbol": freshness.symbol,
                    "timeframe": freshness.timeframe,
                    "state": freshness.state.value,
                    "latest_open_time": (
                        to_iso(freshness.latest_open_time)
                        if freshness.latest_open_time is not None
                        else None
                    ),
                    "checked_at": to_iso(freshness.checked_at),
                    "lag_bars": freshness.lag_bars,
                },
            )
        )

    def _audit_tick_failure(self, trace_id: str, symbol: SymbolTimeframe, error: str) -> None:
        self._audit.append(
            AuditRecord(
                kind="tick.failure",
                trace_id=trace_id,
                payload={
                    "symbol": symbol.symbol,
                    "timeframe": symbol.timeframe,
                    "error": error,
                    "completed_at": to_iso(utcnow()),
                },
            )
        )


def _ts(dt: datetime) -> str:  # pragma: no cover - reserved for future audit fields
    return to_iso(dt)
