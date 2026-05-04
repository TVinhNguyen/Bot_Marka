"""Walk-forward backtest module (issue #10).

Public surface:

* :class:`BacktestConfig`, :class:`CostModel`, :class:`WalkForwardEngine`
* :class:`WalkForwardWindow`, :func:`walk_forward_windows`
* :func:`run_backtest`, :class:`BacktestRunSpec`, :class:`BacktestReport`
* :class:`BacktestMetrics`, :func:`compute_metrics`
"""

from .cost_model import CostModel
from .engine import BacktestConfig, TradeRecord, WalkForwardEngine
from .metrics import BacktestMetrics, compute_metrics, equity_curve, max_drawdown
from .replay import SimulatedFill, estimate_atr, simulate_trade
from .report import BacktestReport, ReportManifest, WindowReport, build_manifest
from .runner import BacktestRunSpec, run_backtest
from .windows import IndexRange, WalkForwardWindow, walk_forward_windows

__all__ = [
    "BacktestConfig",
    "BacktestMetrics",
    "BacktestReport",
    "BacktestRunSpec",
    "CostModel",
    "IndexRange",
    "ReportManifest",
    "SimulatedFill",
    "TradeRecord",
    "WalkForwardEngine",
    "WalkForwardWindow",
    "WindowReport",
    "build_manifest",
    "compute_metrics",
    "equity_curve",
    "estimate_atr",
    "max_drawdown",
    "run_backtest",
    "simulate_trade",
    "walk_forward_windows",
]
