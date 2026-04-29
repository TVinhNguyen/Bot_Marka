---
title: PRD 001 - MT5 Skeleton, Risk Gate, and Execution Safety
labels: [needs-triage]
status: draft
created: 2026-04-29
source_docs: [01-overview.md, 02-architecture.md, 07-risk-management.md, 08-mt5-execution.md, 13-roadmap.md, 16-testing-qa.md, 18-pitfalls.md]
---

# PRD 001 - MT5 Skeleton, Risk Gate, and Execution Safety

## Problem Statement

The project needs a safe first implementation slice that can connect to MetaTrader 5, read market and account state, build broker-valid order requests, and prove that execution plumbing works without sending real orders. Without this foundation, later AI model work could accidentally become coupled to live execution or bypass mandatory risk controls.

The user needs the system to enforce the core rule that forecasts do not trade, ensemble does not size, and only the executor can submit an order after the risk manager approves it.

## Solution

Build the MT5 skeleton as a dry_run-first execution layer with a deterministic risk gate in front of every order request. The system will connect to a demo MT5 terminal, fetch closed bars, account state, symbol metadata, spread, and open positions, then construct an order request and run broker-side validation through order_check. In MVP mode it must never call order_send.

The risk manager will own sizing, SL/TP validation, margin checks, spread checks, drawdown limits, daily limits, position limits, news window checks, soft breakers, and kill switch behavior. The executor will only receive an already approved risk decision and will return structured execution status for audit.

## User Stories

1. As a backend engineer, I want to initialize and reconnect to MT5 reliably, so that the pipeline can run through normal terminal interruptions.
2. As a backend engineer, I want to fetch closed bars for the configured symbol and timeframe, so that downstream logic never uses a running candle.
3. As a backend engineer, I want to fetch tick, spread, symbol info, and account info, so that order requests reflect current broker constraints.
4. As a quant lead, I want dry_run mode to be the default, so that early testing cannot send real orders.
5. As a risk owner, I want every non-HOLD signal to pass through risk evaluation, so that no model can bypass hard limits.
6. As a risk owner, I want max daily loss and max total drawdown enforced, so that the account stops trading before losses exceed configured limits.
7. As a risk owner, I want max open positions and max trades per day enforced, so that the bot cannot overtrade.
8. As a risk owner, I want spread limits enforced per symbol, so that the system avoids trading during expensive market conditions.
9. As a risk owner, I want news window checks to reject trades around high-impact events, so that event risk can block execution.
10. As a risk owner, I want SL and TP to be mandatory for every approved trade, so that no entry can be submitted without bounded risk.
11. As a risk owner, I want position size to scale with confidence and agreement but remain inside hard caps, so that model confidence cannot create excessive exposure.
12. As a risk owner, I want broker stop-level constraints applied to SL and TP, so that order_check does not fail due to invalid distances.
13. As an operator, I want a manual kill switch, so that I can immediately stop new trade decisions.
14. As an operator, I want automatic kill switch triggers for drawdown, repeated execution errors, disconnects, and spread spikes, so that unsafe conditions halt trading without waiting for human action.
15. As an operator, I want restart behavior to preserve kill switch state, so that a service restart cannot accidentally re-enable trading.
16. As an operator, I want reconciliation on startup, so that broker positions and local trade state cannot silently diverge.
17. As an operator, I want order_check results logged in dry_run mode, so that broker validation can be reviewed before demo trading.
18. As an operator, I want order_send timeout handling to avoid automatic retry, so that the system does not double-submit orders.
19. As a reviewer, I want every rejection reason recorded, so that risk behavior is explainable and testable.
20. As a reviewer, I want every execution attempt to include a trace ID, request hash, magic number, comment, and broker retcode, so that each trade can be audited.
21. As a QA engineer, I want integration tests against a demo account, so that MT5 connectivity and order_check behavior are verified in the real broker environment.
22. As a QA engineer, I want property-based tests for position sizing, so that lot size invariants hold across a wide range of account, broker, and market inputs.

## Implementation Decisions

- Build Option A first: Python controls the MT5 terminal directly for MVP and dry_run testing.
- Keep Option B as a later production path: MQL5 EA executor plus Python AI server only after the MVP pipeline is stable.
- Treat the risk manager as a deep module with a stable request-to-decision interface.
- Treat the executor as a narrow deterministic module that accepts only approved risk decisions and never changes lot size, SL, TP, or side by itself.
- Make dry_run the default environment behavior and require explicit configuration to enable order_send.
- Build an MT5 connection component that can initialize, shutdown, reconnect, and expose terminal health.
- Build a market data component that returns closed bars only and exposes spread and symbol metadata.
- Build an account snapshot component that captures equity, balance, free margin, open positions, drawdown, and daily stats.
- Build risk evaluation as pure logic wherever possible, with account and market state passed in as snapshots.
- Enforce hard limits before sizing and before executor submission.
- Implement soft circuit breakers for consecutive losses, daily loss, and weekly loss as risk modifiers or temporary halts.
- Implement a manual kill switch through a file sentinel for MVP, with endpoint and Telegram command left for later environments.
- Use a unique magic number and structured order comment for all bot orders.
- Use idempotency keys for submit attempts and reconcile after timeout instead of retrying order_send.
- Persist all risk decisions, order checks, and execution results in append-only audit records.
- Fail safe to HOLD or reject when account, symbol, spread, or broker constraints are unavailable.

## Testing Decisions

- Good tests assert externally visible behavior: approved versus rejected decisions, computed risk fields, execution status, audit records, and kill switch behavior.
- Do not test private helper implementation details unless they encode externally meaningful math such as lot rounding.
- Unit test all risk reject rules independently.
- Property-test position sizing invariants: risk never exceeds configured caps, volume respects broker min/max/step, SL/TP are present, and risk-reward is valid.
- Unit test executor request building with fake symbol info for filling modes, stop levels, and deviation handling.
- Integration test MT5 connection, closed-bar fetch, symbol selection, account fetch, and order_check on a demo account.
- E2E dry_run test should prove that a mock signal can pass through risk, reach order_check, log the result, and never call order_send.
- Chaos test the kill switch, MT5 disconnect, repeated order_check failures, and crash-before-DB-write reconciliation.

## Out of Scope

- Real-money trading.
- Demo order_send.
- MQL5 EA executor and bridge protocol.
- Trailing stops, partial closes, and advanced position management.
- Multi-account execution.
- Agent orchestration.
- Model inference and ensemble tuning.

## Further Notes

This PRD is the first implementation gate. It should be completed before any model adapter is allowed into a live or demo execution loop.

