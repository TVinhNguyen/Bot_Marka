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
from .data import build_features, load_closed_bars_csv
from .data.forecast_store import JsonlForecastStore
from .domain.bar import Bar
from .domain.forecast import Forecast, MetaSignal
from .domain.market import AccountSnapshot, MarketSnapshot
from .domain.risk import RiskDecision
from .risk import RiskManager
from .risk.kill_switch import FileKillSwitch, KillSwitch
from .utils.logging_setup import get_logger
from .utils.time_utils import to_iso, utcnow
from .utils.tracing import with_trace_id


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
    ) -> None:
        self._cfg = config
        self._audit = audit or JsonlAuditTrail(Path(config.storage.audit_path) / "audit.jsonl")
        self._forecast_store = forecast_store or JsonlForecastStore(
            Path(config.storage.forecasts_path) / "forecasts.jsonl"
        )
        self._kill = kill_switch or FileKillSwitch(config.risk.kill_switch_file)
        self._baseline = baseline or BaselineAdapter()
        self._risk = RiskManager(
            config.risk,
            self._kill,
            magic=config.execution.magic,
            order_comment=config.execution.order_comment,
        )
        self._log = get_logger("ai_mt5.tick")

    # -- public --------------------------------------------------------------

    def run(
        self,
        *,
        bar_fixture_path: str | Path,
        account: AccountSnapshot | None = None,
        market: MarketSnapshot | None = None,
    ) -> TickResult:
        """Run one dry_run tick using ``bar_fixture_path`` for Closed Bars.

        ``account`` and ``market`` snapshots may be supplied by tests or the
        baseline-tick fixture path. When omitted, this slice short-circuits
        the Risk gate: the forecast is still recorded and audited but the
        tick ends in HOLD.
        """
        symbol = self._cfg.primary_symbol()
        with with_trace_id() as trace_id:
            try:
                self._audit_tick_start(trace_id, symbol, bar_fixture_path)
                self._log.info(
                    "tick.start",
                    symbol=symbol.symbol,
                    timeframe=symbol.timeframe,
                    fixture=str(bar_fixture_path),
                    mode=self._cfg.environment.mode,
                )

                bars = load_closed_bars_csv(
                    bar_fixture_path,
                    symbol=symbol.symbol,
                    timeframe=symbol.timeframe,
                )
                if len(bars) < 2:
                    raise ValueError("tick requires at least 2 Closed Bars (history + decision)")

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
