---
title: PRD 004 - Meta-Signal Engine and Walk-Forward Backtesting
labels: [needs-triage]
status: draft
created: 2026-04-29
source_docs: [01-overview.md, 02-architecture.md, 04-models.md, 06-meta-signal.md, 07-risk-management.md, 10-backtesting.md, 13-roadmap.md, 16-testing-qa.md, 18-pitfalls.md]
---

# PRD 004 - Meta-Signal Engine and Walk-Forward Backtesting

## Problem Statement

Multiple model forecasts are only useful if they can be combined into a cost-aware, risk-aware, testable signal that beats baseline after realistic costs. The project must avoid overfitting ensemble weights, assuming agreement is independent evidence, or promoting a strategy from a visually attractive but invalid backtest.

The user needs a meta-signal engine and backtest framework that prove the ensemble has out-of-sample edge before paper, demo, or live trading.

## Solution

Build a pure meta-signal engine that validates model forecasts, rescales active weights, computes raw score, agreement, cost penalty, uncertainty penalty, event penalty, hard vetoes, confidence, and a final BUY/SELL/HOLD decision. The engine returns an auditable ensemble result but never computes lot size and never submits orders.

Build a custom replay backtest engine that walks forward through closed bars, runs adapters or stored predictions, applies the same ensemble and risk modules used by live mode, simulates realistic costs, and reports out-of-sample metrics against mandatory baselines. Promotion is blocked unless the stitched out-of-sample ensemble beats baseline after costs within drawdown limits.

## User Stories

1. As a quant lead, I want all model outputs validated before combination, so that invalid forecasts cannot skew a trade decision.
2. As a quant lead, I want weights rescaled when optional models are unavailable, so that missing adapters do not create hidden score dilution.
3. As a quant lead, I want weighted raw score, agreement, cost penalty, uncertainty penalty, and event penalty recorded, so that every signal is explainable.
4. As a quant lead, I want hard veto rules for model disagreement, high event risk, high spread, low ATR, high realized volatility, weak edge-to-cost, and adapter failures, so that unsafe conditions resolve to HOLD.
5. As a quant lead, I want confidence to derive from agreement and final score, so that risk can scale exposure without trusting any one model absolutely.
6. As a quant lead, I want regime-aware adjustments configurable and disableable, so that they can be tested rather than silently changing behavior.
7. As a quant lead, I want ensemble output to include original component forecasts, so that post-trade attribution can inspect each driver.
8. As a quant lead, I want walk-forward validation with train, validation, and test windows, so that weight tuning does not leak into OOS evaluation.
9. As a quant lead, I want stitched OOS metrics, so that strategy quality is judged by realistic future-like periods.
10. As a quant lead, I want comparisons against Kronos-only, TimesFM-only, Chronos-only, sentiment-only, baseline, and no-trade references, so that ensemble value is measurable.
11. As a quant lead, I want stress tests for doubled spread, doubled slippage, higher commission, missing models, adapter exceptions, latency, and news windows, so that fragile strategies are exposed.
12. As a quant lead, I want a cap on tuning rounds, so that the backtest process does not become manual overfitting.
13. As a quant lead, I want cross-symbol validation, so that tuned behavior does not collapse outside the primary symbol.
14. As a backend engineer, I want the ensemble engine to be pure logic, so that it can be reused by live, backtest, and tests.
15. As a backend engineer, I want the backtest engine to replay bars one by one, so that no future data is visible at forecast time.
16. As a backend engineer, I want the backtest cost model to use realistic spread, commission, slippage, and swap, so that profitability is not overstated.
17. As a backend engineer, I want the risk manager used in backtest, so that simulated trades obey the same limits as live trades.
18. As a backend engineer, I want reports to include commit, config, data snapshot, package lock, seed, and run time, so that results are reproducible.
19. As an operator, I want a clear no-go decision when OOS does not beat baseline, so that the system does not promote weak strategy behavior.
20. As a reviewer, I want decision attribution per model and per penalty, so that review can focus on why trades happened.
21. As a QA engineer, I want deterministic replay fixtures, so that backtest engine changes can be regression-tested.
22. As a QA engineer, I want cost model and walk-forward split tests, so that spread math and time-series splits cannot leak or drift.

## Implementation Decisions

- Treat the ensemble engine as a deep pure module with a stable forecast-list and context input interface.
- Keep ensemble decision output separate from risk decision output.
- Use default weights only as starting values and tune them only inside walk-forward training and validation periods.
- Require minimum model count and adapter validity before any non-HOLD decision.
- Apply hard vetoes before threshold-based BUY or SELL approval.
- Include cost awareness before final thresholds.
- Store every ensemble component and penalty for audit and reporting.
- Use custom backtesting rather than a generic framework as the primary engine, because the system must integrate model forecasts, event risk, risk management, and audit outputs.
- Backtest only closed bars and never slice future bars into feature inputs.
- Prefer real spread data where available; otherwise use broker fixtures and stress tests.
- Make report reproducibility metadata mandatory.
- Define promotion gates around OOS performance, drawdown, stress robustness, and baseline comparison.

## Testing Decisions

- Good tests assert ensemble output behavior for forecast combinations, vetoes, penalties, agreement, and thresholds.
- Unit test each veto rule independently.
- Unit test weight rescaling when one or more models are missing.
- Unit test cost penalty and confidence calculations with deterministic cases.
- Property-test score bounds and HOLD behavior under invalid or insufficient forecasts.
- Unit test replay no-lookahead behavior with fixtures designed to reveal future leaks.
- Unit test walk-forward windows for non-overlap and correct train/validation/test order.
- Unit test metrics against reference calculations.
- Backtest smoke tests should run quickly in CI on small fixtures.
- Full walk-forward reports should run before promotion to demo and whenever signal or risk behavior changes.

## Out of Scope

- Live trading.
- Automated model retraining.
- Agent orchestration for signal decisions.
- Production dashboards.
- Multi-account portfolio backtests.
- Unlimited hyperparameter search.

## Further Notes

If the ensemble does not beat baseline after realistic cost in OOS, the correct output of this PRD is a no-go decision and a tuning backlog, not a demo deployment.

