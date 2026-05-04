"""Agent toolset allowlist + governance."""

from __future__ import annotations

import pytest

from ai_mt5.agent.tools import (
    AGENT_TOOL_ALLOWLIST,
    AgentToolset,
    DenyMutationError,
)
from ai_mt5.baseline.adapter import BaselineAdapter
from ai_mt5.config.models import AppConfig
from ai_mt5.ensemble.ensemble import Ensemble
from ai_mt5.risk.kill_switch import InMemoryKillSwitch
from ai_mt5.risk.manager import RiskManager


def _make_toolset(app_config: AppConfig) -> AgentToolset:
    risk = RiskManager(
        app_config.risk,
        InMemoryKillSwitch(),
        magic=app_config.execution.magic,
        order_comment=app_config.execution.order_comment,
    )
    return AgentToolset(
        config=app_config,
        baseline=BaselineAdapter(),
        adapters=[],
        ensemble=Ensemble(),
        risk=risk,
    )


def test_allowlist_excludes_executor_and_risk_mutation() -> None:
    forbidden = {
        "order_send",
        "modify_risk_config",
        "set_risk_band",
        "engage_kill_switch",
        "release_kill_switch",
        "write_config",
    }
    assert AGENT_TOOL_ALLOWLIST.isdisjoint(forbidden)


def test_allowlist_is_a_known_set() -> None:
    expected = {
        "build_features",
        "run_baseline_forecast",
        "run_adapter_forecast",
        "evaluate_event_risk",
        "combine_meta_signal",
        "evaluate_risk_decision",
    }
    assert expected == AGENT_TOOL_ALLOWLIST


def test_call_rejects_non_allow_listed_tool(app_config: AppConfig) -> None:
    tools = _make_toolset(app_config)
    with pytest.raises(DenyMutationError):
        tools.call("order_send", request={"symbol": "EURUSD", "volume": 1.0})


def test_call_rejects_unknown_tool(app_config: AppConfig) -> None:
    tools = _make_toolset(app_config)
    with pytest.raises(DenyMutationError):
        tools.call("totally_made_up_tool")


def test_adapter_names_exposed(app_config: AppConfig) -> None:
    tools = _make_toolset(app_config)
    assert tools.adapter_names == []


def test_evaluate_event_risk_returns_none_when_unconfigured(app_config: AppConfig) -> None:
    tools = _make_toolset(app_config)
    out = tools.call("evaluate_event_risk", symbol="EURUSD", as_of=None)
    assert out is None
