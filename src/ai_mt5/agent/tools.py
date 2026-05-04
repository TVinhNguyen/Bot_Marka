"""Agent tool allowlist + toolset.

Per issue #12 the Agent Layer must:

* expose a fixed allowlist of read-only tools;
* never expose ``order_send`` or risk-config mutation;
* fail loud when an attempt is made to call a non-allow-listed tool.

The toolset is a thin façade over the same deterministic modules the
straight pipeline uses. It does NOT wrap anything that could mutate
risk state.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..baseline.adapter import BaselineAdapter
from ..config.models import AppConfig
from ..data.features import FeatureSet, build_features
from ..domain.bar import Bar
from ..domain.forecast import Forecast, MetaSignal
from ..domain.market import AccountSnapshot, MarketSnapshot
from ..domain.risk import RiskDecision
from ..ensemble.ensemble import Ensemble
from ..models.protocol import AdapterError, ModelAdapter
from ..risk.manager import RiskManager
from ..text.event_risk import EventRiskAdapter, EventRiskOutput

AGENT_TOOL_ALLOWLIST: frozenset[str] = frozenset(
    {
        "build_features",
        "run_baseline_forecast",
        "run_adapter_forecast",
        "evaluate_event_risk",
        "combine_meta_signal",
        "evaluate_risk_decision",
    }
)
"""The complete set of tool names the Agent Layer is allowed to invoke.

Any change here is a governance change and must come with an ADR update.
"""

# Names that MUST never appear in the allowlist. We assert this at import
# time so reviewers cannot accidentally widen the surface in a refactor.
_FORBIDDEN_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "order_send",
        "modify_risk_config",
        "set_risk_band",
        "engage_kill_switch",
        "release_kill_switch",
        "write_config",
        "force_open_position",
    }
)


def _assert_allowlist_safe() -> None:
    overlap = AGENT_TOOL_ALLOWLIST & _FORBIDDEN_TOOL_NAMES
    if overlap:
        raise RuntimeError(f"agent tool allowlist contains forbidden tools: {sorted(overlap)}")


_assert_allowlist_safe()


class DenyMutationError(RuntimeError):
    """Raised when the agent tries to call a non-allow-listed tool."""


@dataclass(frozen=True)
class _ToolBindings:
    config: AppConfig
    baseline: BaselineAdapter
    adapters: list[ModelAdapter]
    ensemble: Ensemble
    risk: RiskManager
    event_risk: EventRiskAdapter | None


class AgentToolset:
    """Allow-listed read-only API the agent may call.

    Each public method is a "tool". Methods explicitly named outside
    :data:`AGENT_TOOL_ALLOWLIST` raise :class:`DenyMutationError` when
    accessed via :meth:`call`.
    """

    def __init__(
        self,
        *,
        config: AppConfig,
        baseline: BaselineAdapter,
        adapters: list[ModelAdapter],
        ensemble: Ensemble,
        risk: RiskManager,
        event_risk: EventRiskAdapter | None = None,
    ) -> None:
        self._b = _ToolBindings(
            config=config,
            baseline=baseline,
            adapters=adapters,
            ensemble=ensemble,
            risk=risk,
            event_risk=event_risk,
        )

    @property
    def allowed(self) -> frozenset[str]:
        return AGENT_TOOL_ALLOWLIST

    @property
    def adapter_names(self) -> list[str]:
        return [a.name for a in self._b.adapters]

    def call(self, name: str, /, **kwargs: Any) -> Any:
        """Dispatch through a single chokepoint so the allowlist is enforced."""
        if name not in AGENT_TOOL_ALLOWLIST:
            raise DenyMutationError(
                f"tool {name!r} is not on the agent allowlist; "
                f"available={sorted(AGENT_TOOL_ALLOWLIST)}"
            )
        method: Callable[..., Any] = getattr(self, name)
        return method(**kwargs)

    # -- allowed tools -----------------------------------------------------

    def build_features(self, *, history: list[Bar], decision_bar: Bar) -> FeatureSet:
        return build_features(history, decision_bar=decision_bar)

    def run_baseline_forecast(
        self, *, features: FeatureSet, symbol: str, timeframe: str
    ) -> Forecast:
        return self._b.baseline.forecast(features, symbol=symbol, timeframe=timeframe)

    def run_adapter_forecast(
        self,
        *,
        adapter_name: str,
        features: FeatureSet,
        symbol: str,
        timeframe: str,
    ) -> Forecast:
        adapter = next(
            (a for a in self._b.adapters if a.name == adapter_name),
            None,
        )
        if adapter is None:
            raise AdapterError(f"unknown adapter {adapter_name!r}")
        return adapter.forecast(features, symbol=symbol, timeframe=timeframe)

    def evaluate_event_risk(self, *, symbol: str, as_of: Any) -> EventRiskOutput | None:
        if self._b.event_risk is None:
            return None
        return self._b.event_risk.evaluate(symbol=symbol, as_of=as_of)

    def combine_meta_signal(
        self,
        *,
        forecasts: list[Forecast],
        spread_points: int,
        n_adapter_failures: int,
        n_adapter_total: int,
        event_risk: EventRiskOutput | None,
    ) -> MetaSignal:
        return self._b.ensemble.combine(
            forecasts,
            event_risk=event_risk,
            spread_points=spread_points,
            n_adapter_failures=n_adapter_failures,
            n_adapter_total=n_adapter_total,
        )

    def evaluate_risk_decision(
        self,
        *,
        signal: MetaSignal,
        account: AccountSnapshot,
        market: MarketSnapshot,
        now: Any,
    ) -> RiskDecision:
        return self._b.risk.evaluate(signal, account, market, now=now)
