# 0008 -- Walk-forward backtest engine

Status: Accepted
Date: 2026-04-29

## Context

Issue #10 requires an out-of-sample, walk-forward backtest that drives the
same Baseline + Adapter + Ensemble + Risk Decision pipeline that
`dry_run_tick` uses, simulates realistic broker frictions, and emits
reports reproducible from the inputs alone. Without it we cannot compare
the ensemble against the Baseline on historical data, and we cannot prove
that a configuration change is safe before promoting it to demo / live.

## Decision

Introduce `ai_mt5/backtest/` with a thin, composable surface:

* `CostModel` -- pure dataclass for spread / commission / slippage buffer
  / overnight swap. Only the engine knows how to apply it; the model
  itself never reads config.
* `WalkForwardWindow` + `walk_forward_windows()` -- index-based splitter
  that emits ordered, non-overlapping `(train | validation | oos)`
  ranges. Test surface is index-only so the splitter can be reused for
  CSV fixtures, in-memory bars, or BarStore output without I/O.
* `simulate_trade()` + `estimate_atr()` -- bar-by-bar replay that opens a
  trade at the close of the decision bar and walks forward until SL or
  TP is touched (SL checked first; conservative). The decision bar can
  never also exit the trade (`range(entry_idx + 1, ...)`). ATR uses only
  bars strictly past the decision index.
* `WalkForwardEngine` -- runs two pipelines in lockstep over a window:
  `baseline` (Baseline forecast wrapped in a single-model MetaSignal) and
  `ensemble` (all adapters into `Ensemble.combine()`). Both go through
  the *same* `RiskManager` so confidence/agreement sizing (ADR 0007)
  applies identically.
* `BacktestMetrics` + `compute_metrics()` -- OOS PnL, drawdown, Sharpe,
  Calmar, profit factor, win rate, trade count, average trade. Sharpe
  annualises on `bars_per_year / max(bars_per_trade, 1)`. Calmar uses
  fractional drawdown so the unit is dimensionless. Profit factor is
  `+inf` when there are no losers (serialised as the string `"inf"` so
  the JSON stays RFC 8259 compliant).
* `ReportManifest` -- captures `commit` (git rev-parse, `"unknown"` when
  missing), `config_hash` (sha256 of the config dict, sorted keys),
  `data_snapshot_hash` (sha256 of the OHLCV + spread bar series),
  `package_lock_hash` (uv.lock sha256), `seed`, `run_timestamp`,
  `n_bars`, `symbol`, `timeframe`. Two runs with the same inputs MUST
  produce the same manifest hashes.
* CLI: `ai-mt5 backtest --config ... --bars ... [--train --validation
  --oos --step --initial-equity --seed --spread-points
  --commission-per-lot --slippage-buffer-points --out]`. Emits a JSON
  report and prints a one-line summary (output path, window count,
  manifest, baseline-vs-ensemble comparison).

## Consequences

* No new run-time dependency on MT5; backtests run anywhere the rest of
  the offline pipeline runs.
* Reports are deterministic: re-running the same `(bars, config, seed)`
  yields the same manifest hashes and the same trade ledger. CI
  regression tests assert this.
* Baseline-vs-ensemble comparison is part of the aggregate report
  (`delta_gross_pnl`, `delta_sharpe`, `delta_max_drawdown_pct`,
  `delta_win_rate`, `delta_n_trades`).
* The replay's exit ordering (SL before TP within a single bar) is
  intentionally conservative; backtest results may underestimate
  realistic fill prices when both levels sit inside a single bar's
  range. We accept this rather than coin-flip the order.
* Costs do not currently include funding for held positions during the
  weekend (a triple-swap night). The cost model exposes per-side
  `swap_*_per_night` so a follow-up can multiply the Friday rollover by
  3 without touching the engine.

## Alternatives considered

* Time-based windows (e.g. "last 4 weeks"). Rejected because the same
  index-based splitter can be fed time-bucketed bars by the caller, and
  tests stay independent of broker session conventions.
* Vectorised PnL with a single matrix step. Rejected because it forces
  the same anti-leak invariants to be re-proven in a different shape;
  the bar-by-bar loop reuses the existing `build_features` /
  `compute_sl_tp` paths verbatim.
* Folding the cost model into the engine. Rejected because the cost
  model is the part most likely to be swapped per-symbol; keeping it
  pure makes the engine reusable across instruments.
