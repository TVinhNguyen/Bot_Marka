---
title: Run walk-forward backtest with baseline comparison
labels: [needs-triage]
type: AFK
---

## What to build

Create the Walk-Forward Backtest path that replays Closed Bars, consumes stored Forecasts or adapters, runs the same Ensemble and Risk Decision logic used by dry_run, simulates realistic costs, and produces out-of-sample metrics against the Baseline and per-model references.

## Acceptance criteria

- [ ] Replay advances bar by bar without future data access.
- [ ] Walk-forward windows separate train, validation, and out-of-sample periods.
- [ ] Cost model includes spread, commission, slippage buffer, and swap where available.
- [ ] The Risk Decision module is used in simulated trades.
- [ ] Reports include OOS metrics, drawdown, Sharpe, Calmar, profit factor, trade count, and model/baseline comparisons.
- [ ] Reports include commit, config, data snapshot, package lock, seed, and run timestamp.
- [ ] Tests cover no-lookahead replay, split boundaries, cost model math, and metric calculations.

## Blocked by

- Enforce Risk Decision gate with sizing, SL/TP, and kill switch.
- Backfill market data store with quality gates.
- Produce auditable Meta-Signal from stored Forecasts.

