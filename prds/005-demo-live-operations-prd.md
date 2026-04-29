---
title: PRD 005 - Paper, Demo, Staging, and Small Live Deployment
labels: [needs-triage]
status: draft
created: 2026-04-29
source_docs: [01-overview.md, 07-risk-management.md, 08-mt5-execution.md, 10-backtesting.md, 13-roadmap.md, 14-deployment.md, 15-monitoring.md, 16-testing-qa.md, 17-security.md, 18-pitfalls.md]
---

# PRD 005 - Paper, Demo, Staging, and Small Live Deployment

## Problem Statement

Even a profitable backtest can fail live due to slippage, stale data, broker constraints, disconnects, clock drift, operational mistakes, and regime changes. The system needs a controlled promotion path that proves reliability before any real-money exposure.

The user needs dry_run, shadow, demo, staging, and small live environments with clear entry gates, rollback, monitoring, incident response, and risk limits.

## Solution

Implement an operations and deployment workflow that promotes the system one environment at a time: dev, dry_run, demo, staging, and live. Each promotion requires passing tests, config validation, audit readiness, backtest reports, shadow comparison, demo soak, kill switch drills, and operator readiness.

Live begins with one symbol, one timeframe, risk per trade of 0.05% to 0.1%, max daily loss of 0.5%, and max total drawdown of 3%. Size increases only after four-week review cycles and only if live metrics remain within risk and performance thresholds.

## User Stories

1. As an operator, I want separate dev, dry_run, demo, staging, and live modes, so that risk exposure is explicit.
2. As an operator, I want promotion to move only forward through the environments, so that the system cannot skip safety gates.
3. As an operator, I want dry_run to run without order_send for at least three days, so that data, logs, and order_check behavior can be observed safely.
4. As an operator, I want shadow mode to save live signals without placing orders, so that forecasts can be compared against actual market behavior.
5. As an operator, I want demo trading to run for 2-4 weeks, so that execution reliability can be measured before live.
6. As an operator, I want first live deployment to use one symbol and one timeframe, so that operational complexity stays limited.
7. As an operator, I want live risk per trade capped at 0.05% to 0.1% initially, so that early real-money exposure is small.
8. As an operator, I want kill switch drills before live, so that stopping the system is practiced rather than theoretical.
9. As an operator, I want reconcile-on-start tested before demo and live, so that restarts cannot create unknown positions.
10. As an operator, I want alerting validated before promotion, so that critical failures reach the right channel quickly.
11. As an operator, I want rollback by commit and config snapshot, so that bad deployments can be reverted without rewriting history.
12. As an operator, I want log rotation and disk monitoring, so that logs do not silently stop during trading.
13. As an operator, I want time sync checks, so that clock drift does not corrupt bar alignment or execution timing.
14. As a quant lead, I want live or demo performance compared with backtest for the same period, so that drift is visible.
15. As a quant lead, I want size increases reviewed every four weeks, so that winning streaks do not cause impulsive scaling.
16. As a quant lead, I want no-go gates when shadow or demo is materially worse than backtest, so that weak live behavior triggers investigation.
17. As a risk owner, I want live drawdown limits stricter than research limits, so that real-money rollout starts conservatively.
18. As a risk owner, I want risk config changes reviewed before live deployment, so that exposure settings cannot be changed casually.
19. As a backend engineer, I want deployment to support single Windows VPS first, so that MT5 and Python can run in the simplest topology.
20. As a backend engineer, I want split MT5 host and AI server documented as a later topology, so that production can scale without blocking MVP.
21. As a security reviewer, I want secrets validated and absent from git before promotion, so that credentials are not exposed.
22. As a QA engineer, I want chaos tests before live, so that disconnects, adapter failures, DB locks, disk full, and kill switch behavior are verified.
23. As a reviewer, I want every deployment to record commit, config snapshot, and data snapshot, so that incidents can be traced.

## Implementation Decisions

- Use a strict promotion sequence: dev to dry_run to demo to staging to live.
- Make dry_run required before demo and shadow required before live.
- Use single-machine Windows VPS as the simplest MVP deployment target.
- Keep split MT5 host and AI server as the production path after demo stability.
- Require pre-deploy checks for tests, config validation, secrets, disk, log rotation, monitoring, kill switch, reconciliation, DB schema, and backups.
- Use service supervision appropriate to the host environment.
- Store deployment commit and config snapshots for rollback and audit.
- Do not allow direct live config edits on the server; require reviewed changes and redeploy.
- Require updated OOS backtest reports before promotion to demo or live.
- Start live with smaller risk limits than research defaults.
- Require operator runbooks for stop, restart, rollback, MT5 disconnect, order timeout, DB issue, and security incident.
- Treat repeated SLO violations as incident-review triggers.

## Testing Decisions

- Good operations tests prove behavior under realistic failures and promotion gates, not only happy-path startup.
- Run unit, property, integration, and backtest smoke tests before dry_run.
- Run demo MT5 integration tests before demo promotion.
- Run shadow comparison for 2-4 weeks before live.
- Run chaos tests for MT5 disconnect, adapter exception, missing news, DB lock, kill switch, disk pressure, clock drift, and adapter latency.
- Test alert channels manually before demo and live.
- Test restore from backup before live.
- Test rollback procedure on staging before live.
- Test that live mode refuses startup when required secrets or config constraints are missing.

## Out of Scope

- Large live size.
- Multi-symbol live expansion.
- Fully managed cloud production.
- MQL5 EA production executor unless chosen after MVP.
- Automated model retraining or self-healing strategy changes.
- Legal or regulatory clearance beyond documentation and record keeping.

## Further Notes

This PRD is about operational readiness, not adding new alpha. A strategy that passes research but fails operations should not go live.

