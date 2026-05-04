"""High-level walk-forward backtest orchestrator.

Glues :mod:`windows`, :mod:`engine`, :mod:`metrics`, and :mod:`report`
into a single ``run_backtest`` function that the CLI and tests share.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..baseline.adapter import BaselineAdapter
from ..domain.bar import Bar
from ..models.protocol import ModelAdapter
from .engine import BacktestConfig, TradeRecord, WalkForwardEngine
from .metrics import compute_metrics
from .replay import bar_duration
from .report import (
    BacktestReport,
    WindowReport,
    build_manifest,
    summarise_pipeline,
)
from .windows import WalkForwardWindow, walk_forward_windows


@dataclass(frozen=True)
class BacktestRunSpec:
    """Inputs for one run of the backtester."""

    config: BacktestConfig
    train: int
    validation: int
    oos: int
    step: int | None = None
    seed: int = 0


def run_backtest(
    bars: list[Bar],
    *,
    spec: BacktestRunSpec,
    adapters: list[ModelAdapter] | None = None,
    repo_root: Path | None = None,
    config_for_manifest: dict[str, Any] | None = None,
) -> BacktestReport:
    """Run the full walk-forward pipeline and return a report.

    ``adapters`` defaults to ``[BaselineAdapter()]``. ``config_for_manifest``
    is the *plain dict* form of the config used; supply the loaded config
    directly so the manifest hash matches what an operator would see.
    """
    if not bars:
        raise ValueError("run_backtest requires a non-empty bar list")
    if adapters is None:
        adapters = [BaselineAdapter()]

    # Auto-detect bar density if the caller didn't override it; otherwise
    # honour the configured ``bar_seconds`` as authoritative.
    config = spec.config
    if config.bar_seconds <= 0:
        seconds = bar_duration(bars).total_seconds()
        if seconds <= 0:
            seconds = 900.0
        config = BacktestConfig(
            symbol=config.symbol,
            timeframe=config.timeframe,
            initial_equity=config.initial_equity,
            risk=config.risk,
            cost_model=config.cost_model,
            warmup_bars=config.warmup_bars,
            atr_window=config.atr_window,
            bar_seconds=seconds,
            magic=config.magic,
            order_comment=config.order_comment,
            ensemble_config=config.ensemble_config,
        )

    engine = WalkForwardEngine(config, adapters=list(adapters))
    windows = list(
        walk_forward_windows(
            len(bars),
            train=spec.train,
            validation=spec.validation,
            oos=spec.oos,
            step=spec.step,
        )
    )
    if not windows:
        raise ValueError("no walk-forward windows fit the bar series")

    manifest = build_manifest(
        config=config_for_manifest or {},
        bars=bars,
        seed=spec.seed,
        repo_root=repo_root,
    )

    window_reports: list[WindowReport] = []
    aggregate_pnls: dict[str, list[float]] = {"baseline": [], "ensemble": []}
    aggregate_trades: dict[str, list[TradeRecord]] = {"baseline": [], "ensemble": []}
    aggregate_equity_track: dict[str, float] = {
        "baseline": config.initial_equity,
        "ensemble": config.initial_equity,
    }
    aggregate_decisions: dict[str, int] = {"baseline": 0, "ensemble": 0}
    aggregate_rejections: dict[str, int] = {"baseline": 0, "ensemble": 0}
    aggregate_vetoes: dict[str, int] = {"baseline": 0, "ensemble": 0}

    for idx, window in enumerate(windows):
        states = engine.run_window(bars, window)
        per_pipeline: dict[str, dict[str, Any]] = {}
        for name, state in states.items():
            metrics = compute_metrics(
                [t.net_pnl for t in state.trades],
                initial_equity=config.initial_equity,
                bars_per_year=config.bars_per_year,
                bars_per_trade=_avg_bars_held(state.trades),
            )
            per_pipeline[name] = summarise_pipeline(
                metrics=metrics,
                trades=state.trades,
                decisions=state.decisions,
                rejections=state.rejections,
                veto_count=state.veto_count,
                final_equity=state.equity,
                initial_equity=config.initial_equity,
            )
            aggregate_pnls[name].extend(t.net_pnl for t in state.trades)
            aggregate_trades[name].extend(state.trades)
            aggregate_equity_track[name] += state.equity - config.initial_equity
            aggregate_decisions[name] += state.decisions
            aggregate_rejections[name] += state.rejections
            aggregate_vetoes[name] += state.veto_count

        window_reports.append(
            WindowReport(
                window_index=idx,
                train_start=window.train.start,
                train_end=window.train.end,
                validation_end=window.validation.end,
                oos_end=window.oos.end,
                pipelines=per_pipeline,
            )
        )

    aggregate: dict[str, dict[str, Any]] = {}
    for name in ("baseline", "ensemble"):
        metrics = compute_metrics(
            aggregate_pnls[name],
            initial_equity=config.initial_equity,
            bars_per_year=config.bars_per_year,
            bars_per_trade=_avg_bars_held(aggregate_trades[name]),
        )
        aggregate[name] = summarise_pipeline(
            metrics=metrics,
            trades=aggregate_trades[name],
            decisions=aggregate_decisions[name],
            rejections=aggregate_rejections[name],
            veto_count=aggregate_vetoes[name],
            final_equity=aggregate_equity_track[name],
            initial_equity=config.initial_equity,
        )
    aggregate["comparison"] = _compare_pipelines(aggregate)

    return BacktestReport(manifest=manifest, windows=window_reports, aggregate=aggregate)


def _avg_bars_held(trades: list[TradeRecord]) -> float:
    if not trades:
        return 1.0
    total = sum(max(t.fill.bars_held, 1) for t in trades)
    return total / len(trades)


def _compare_pipelines(aggregate: dict[str, dict[str, Any]]) -> dict[str, Any]:
    base = aggregate["baseline"]["metrics"]
    ens = aggregate["ensemble"]["metrics"]
    return {
        "delta_gross_pnl": ens["gross_pnl"] - base["gross_pnl"],
        "delta_sharpe": ens["sharpe"] - base["sharpe"],
        "delta_max_drawdown_pct": ens["max_drawdown_pct"] - base["max_drawdown_pct"],
        "delta_win_rate": ens["win_rate"] - base["win_rate"],
        "delta_n_trades": ens["n_trades"] - base["n_trades"],
    }


_ = (WalkForwardWindow,)  # silence unused-import lint
