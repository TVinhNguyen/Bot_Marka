"""Agent Layer that orchestrates the deterministic pipeline.

Determinism contract: ``run_tick`` must return the same
``(MetaSignal, RiskDecision)`` as the straight :class:`TickRunner` for the
same inputs. The agent's only freedom is the narration text and (in
future) the order in which it calls allow-listed tools -- never *what*
the deterministic modules return.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from ..domain.bar import Bar
from ..domain.forecast import Forecast, MetaSignal
from ..domain.market import AccountSnapshot, MarketSnapshot
from ..domain.risk import RiskDecision
from ..models.protocol import AdapterError
from ..text.event_risk import EventRiskOutput
from .narration import (
    AgentNarration,
    NarrationValidationError,
    narration_matches,
    validate_narration,
)
from .tools import AgentToolset


class NarrationFallback(StrEnum):
    """Why a deterministic fallback narration was used in place of the agent's."""

    NONE = "none"
    INVALID_SCHEMA = "invalid_schema"
    DISAGREES_WITH_DECISION = "disagrees_with_decision"
    NO_NARRATOR = "no_narrator"


@dataclass(frozen=True)
class AgentResult:
    """Output of one agent-orchestrated tick.

    The deterministic ``signal`` and ``decision`` are returned verbatim;
    ``narration`` and ``narration_fallback`` describe the agent overlay.
    """

    signal: MetaSignal
    decision: RiskDecision
    narration: AgentNarration
    narration_fallback: NarrationFallback
    forecasts: list[Forecast]


# Type alias for narrators. A real implementation may call an LLM; tests
# inject a deterministic stub.
Narrator = Callable[[dict[str, Any]], dict[str, Any]]


def _deterministic_narration(
    *,
    trace_id: str,
    signal: MetaSignal,
    decision: RiskDecision,
) -> AgentNarration:
    rejected = list(decision.rejected_by)
    if decision.approved:
        rationale = (
            f"deterministic decision: {signal.direction}, "
            f"final_score={signal.final_score:.4f}, agreement={signal.agreement:.2f}"
        )
    else:
        rationale = (
            f"deterministic decision: HOLD; rejected_by={','.join(rejected) if rejected else 'n/a'}"
        )
    return AgentNarration(
        trace_id=trace_id,
        direction=signal.direction,
        approved=decision.approved,
        rationale=rationale[:400],
        rejection_reasons=rejected,
        recommended_followups=[],
    )


class AgentLayer:
    """Wraps the deterministic pipeline behind an allow-listed toolset.

    The layer never makes the trading decision: it always invokes the
    deterministic ``RiskManager`` (via the toolset) and returns whatever
    that returns. The agent's freedom is limited to:

    * orchestration (the order tools are called) -- but the inputs and
      outputs of each tool are fixed;
    * narration (text describing the decision) -- validated against the
      :class:`AgentNarration` schema; falls back to a deterministic
      narration if the agent's version is invalid or disagrees.
    """

    def __init__(
        self,
        toolset: AgentToolset,
        *,
        narrator: Narrator | None = None,
    ) -> None:
        self._tools = toolset
        self._narrator = narrator

    def run_tick(
        self,
        *,
        trace_id: str,
        symbol: str,
        timeframe: str,
        bars: list[Bar],
        account: AccountSnapshot,
        market: MarketSnapshot,
        decision_time: datetime,
        spread_points: int,
        n_adapter_total: int,
    ) -> AgentResult:
        if len(bars) < 2:
            raise ValueError("agent tick requires at least 2 bars (history + decision)")
        history = bars[:-1]
        decision_bar = bars[-1]

        features = self._tools.call("build_features", history=history, decision_bar=decision_bar)

        baseline_forecast = self._tools.call(
            "run_baseline_forecast",
            features=features,
            symbol=symbol,
            timeframe=timeframe,
        )
        forecasts: list[Forecast] = [baseline_forecast]
        n_failures = 0
        for adapter_name in self._tools.adapter_names:
            try:
                forecasts.append(
                    self._tools.call(
                        "run_adapter_forecast",
                        adapter_name=adapter_name,
                        features=features,
                        symbol=symbol,
                        timeframe=timeframe,
                    )
                )
            except AdapterError:
                n_failures += 1

        event_risk: EventRiskOutput | None = self._tools.call(
            "evaluate_event_risk", symbol=symbol, as_of=decision_bar.open_time
        )

        signal = self._tools.call(
            "combine_meta_signal",
            forecasts=forecasts,
            spread_points=spread_points,
            n_adapter_failures=n_failures,
            n_adapter_total=n_adapter_total,
            event_risk=event_risk,
        )
        decision = self._tools.call(
            "evaluate_risk_decision",
            signal=signal,
            account=account,
            market=market,
            now=decision_time,
        )

        narration, fallback = self._narrate(trace_id=trace_id, signal=signal, decision=decision)
        return AgentResult(
            signal=signal,
            decision=decision,
            narration=narration,
            narration_fallback=fallback,
            forecasts=forecasts,
        )

    # -- internals -----------------------------------------------------------

    def _narrate(
        self, *, trace_id: str, signal: MetaSignal, decision: RiskDecision
    ) -> tuple[AgentNarration, NarrationFallback]:
        if self._narrator is None:
            return (
                _deterministic_narration(trace_id=trace_id, signal=signal, decision=decision),
                NarrationFallback.NO_NARRATOR,
            )
        prompt: dict[str, Any] = {
            "trace_id": trace_id,
            "direction": signal.direction,
            "approved": decision.approved,
            "rejected_by": list(decision.rejected_by),
            "agreement": signal.agreement,
            "final_score": signal.final_score,
        }
        try:
            raw = self._narrator(prompt)
        except Exception:
            return (
                _deterministic_narration(trace_id=trace_id, signal=signal, decision=decision),
                NarrationFallback.INVALID_SCHEMA,
            )
        try:
            parsed = validate_narration(raw)
        except NarrationValidationError:
            return (
                _deterministic_narration(trace_id=trace_id, signal=signal, decision=decision),
                NarrationFallback.INVALID_SCHEMA,
            )
        if not narration_matches(parsed, direction=signal.direction, approved=decision.approved):
            return (
                _deterministic_narration(trace_id=trace_id, signal=signal, decision=decision),
                NarrationFallback.DISAGREES_WITH_DECISION,
            )
        return parsed, NarrationFallback.NONE
