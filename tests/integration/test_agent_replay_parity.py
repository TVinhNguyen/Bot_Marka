"""Replay parity: Agent Layer must match the straight pipeline.

Per issue #12, the Agent Layer is allowed to *narrate* but never to flip
the decision. For the same ``(bars, config, seed)`` the agent path must
produce the same MetaSignal direction, the same RiskDecision (approved
flag and rejection reasons), and the same forecast set as the
deterministic ``TickRunner`` -- otherwise the agent has injected
non-determinism the audit chain cannot prove against.
"""

from __future__ import annotations

from pathlib import Path

from ai_mt5.agent.layer import AgentLayer, NarrationFallback
from ai_mt5.agent.tools import AgentToolset
from ai_mt5.baseline.adapter import BaselineAdapter
from ai_mt5.config.models import AppConfig
from ai_mt5.data import load_closed_bars_csv
from ai_mt5.domain.market import AccountSnapshot, MarketSnapshot
from ai_mt5.ensemble.ensemble import Ensemble
from ai_mt5.risk.kill_switch import InMemoryKillSwitch
from ai_mt5.risk.manager import RiskManager
from ai_mt5.tick import TickRunner


def _run_straight(
    app_config: AppConfig,
    bars_path: Path,
    account: AccountSnapshot,
    market: MarketSnapshot,
):
    runner = TickRunner(app_config)
    return runner.run(bar_fixture_path=bars_path, account=account, market=market)


def _run_agent(
    app_config: AppConfig,
    bars_path: Path,
    account: AccountSnapshot,
    market: MarketSnapshot,
):
    sym = app_config.primary_symbol()
    bars = load_closed_bars_csv(bars_path, symbol=sym.symbol, timeframe=sym.timeframe)
    risk = RiskManager(
        app_config.risk,
        InMemoryKillSwitch(),
        magic=app_config.execution.magic,
        order_comment=app_config.execution.order_comment,
    )
    tools = AgentToolset(
        config=app_config,
        baseline=BaselineAdapter(),
        adapters=[],
        ensemble=Ensemble(),
        risk=risk,
    )
    layer = AgentLayer(tools)
    return layer.run_tick(
        trace_id="agent-replay-1",
        symbol=sym.symbol,
        timeframe=sym.timeframe,
        bars=bars,
        account=account,
        market=market,
        decision_time=bars[-1].open_time,
        spread_points=float(bars[-1].spread_points),
        n_adapter_total=1,  # baseline only
    )


def test_agent_path_matches_straight_pipeline(
    app_config, fixture_bars_path, account_snapshot, market_snapshot
) -> None:
    """Same inputs -> same direction, same approval, same rejection set."""
    straight = _run_straight(app_config, fixture_bars_path, account_snapshot, market_snapshot)
    agent = _run_agent(app_config, fixture_bars_path, account_snapshot, market_snapshot)

    assert straight.status == "success"
    assert straight.forecast is not None
    assert straight.risk_decision is not None

    # Direction parity (Baseline forecast direction).
    assert agent.forecasts[0].direction == straight.forecast.direction

    # Approval and rejection parity.
    assert agent.decision.approved == straight.risk_decision.approved
    assert sorted(agent.decision.rejected_by) == sorted(straight.risk_decision.rejected_by)


def test_agent_falls_back_when_narrator_disagrees(
    app_config, fixture_bars_path, account_snapshot, market_snapshot
) -> None:
    """A narrator that flips the direction must be discarded for the deterministic narration."""
    sym = app_config.primary_symbol()
    bars = load_closed_bars_csv(fixture_bars_path, symbol=sym.symbol, timeframe=sym.timeframe)
    risk = RiskManager(
        app_config.risk,
        InMemoryKillSwitch(),
        magic=app_config.execution.magic,
        order_comment=app_config.execution.order_comment,
    )
    tools = AgentToolset(
        config=app_config,
        baseline=BaselineAdapter(),
        adapters=[],
        ensemble=Ensemble(),
        risk=risk,
    )

    def evil_narrator(prompt):
        return {
            "trace_id": prompt["trace_id"],
            "direction": "SELL" if prompt["direction"] == "BUY" else "BUY",
            "approved": prompt["approved"],
            "rationale": "agent override",
            "rejection_reasons": prompt.get("rejected_by", []),
            "recommended_followups": [],
        }

    layer = AgentLayer(tools, narrator=evil_narrator)
    out = layer.run_tick(
        trace_id="evil",
        symbol=sym.symbol,
        timeframe=sym.timeframe,
        bars=bars,
        account=account_snapshot,
        market=market_snapshot,
        decision_time=bars[-1].open_time,
        spread_points=float(bars[-1].spread_points),
        n_adapter_total=1,
    )
    assert out.narration_fallback in {
        NarrationFallback.DISAGREES_WITH_DECISION,
        NarrationFallback.INVALID_SCHEMA,
    }
    # The deterministic decision survives the narrator's override.
    assert out.narration.direction == out.signal.direction
    assert out.narration.approved == out.decision.approved


def test_agent_falls_back_on_narrator_exception(
    app_config, fixture_bars_path, account_snapshot, market_snapshot
) -> None:
    sym = app_config.primary_symbol()
    bars = load_closed_bars_csv(fixture_bars_path, symbol=sym.symbol, timeframe=sym.timeframe)
    risk = RiskManager(
        app_config.risk,
        InMemoryKillSwitch(),
        magic=app_config.execution.magic,
        order_comment=app_config.execution.order_comment,
    )
    tools = AgentToolset(
        config=app_config,
        baseline=BaselineAdapter(),
        adapters=[],
        ensemble=Ensemble(),
        risk=risk,
    )

    def boom(_prompt):
        raise RuntimeError("LLM provider down")

    layer = AgentLayer(tools, narrator=boom)
    out = layer.run_tick(
        trace_id="boom",
        symbol=sym.symbol,
        timeframe=sym.timeframe,
        bars=bars,
        account=account_snapshot,
        market=market_snapshot,
        decision_time=bars[-1].open_time,
        spread_points=float(bars[-1].spread_points),
        n_adapter_total=1,
    )
    assert out.narration_fallback is NarrationFallback.INVALID_SCHEMA
    assert out.narration.direction == out.signal.direction


def test_agent_with_no_narrator_uses_deterministic_narration(
    app_config, fixture_bars_path, account_snapshot, market_snapshot
) -> None:
    out = _run_agent(app_config, fixture_bars_path, account_snapshot, market_snapshot)
    assert out.narration_fallback is NarrationFallback.NO_NARRATOR
    assert out.narration.direction == out.signal.direction
    assert out.narration.approved == out.decision.approved
