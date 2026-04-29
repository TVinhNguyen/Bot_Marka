---
title: Operate Shadow Mode and promotion gates
labels: [needs-triage]
type: HITL
---

## What to build

Add the operational path for Shadow Mode and environment promotion. The system should run on live data without placing trades, record Forecasts, Meta-Signals, Risk Decisions, and outcomes, and enforce documented gates before demo or Small Live promotion.

## Acceptance criteria

- [ ] Environment modes distinguish dev, dry_run, Shadow Mode, demo, staging, and Small Live.
- [ ] Shadow Mode records live-data decisions without order_send.
- [ ] Shadow reports compare captured decisions with later market outcomes and relevant backtest behavior.
- [ ] Promotion checklist verifies tests, config validation, secrets, monitoring, kill switch, reconciliation, backup, and current backtest report.
- [ ] Small Live defaults enforce one symbol-timeframe and reduced risk limits.
- [ ] Rollback uses commit and config snapshot references.
- [ ] Runbooks cover stop, restart, rollback, MT5 disconnect, order timeout, DB issue, and security incident.

## Blocked by

- Verify MT5 demo Closed Bar preflight and dry_run order_check.
- Reconcile broker and local trade state after startup or timeout.
- Run walk-forward backtest with baseline comparison.

