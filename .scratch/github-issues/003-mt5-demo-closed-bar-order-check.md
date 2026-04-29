---
title: Verify MT5 demo Closed Bar preflight and dry_run order_check
labels: [needs-triage]
type: HITL
---

## What to build

Add an MT5 demo-account preflight that connects to the configured terminal, fetches account and symbol state, loads EURUSD M15 Closed Bars, builds a broker-valid request from a synthetic approved decision, and runs order_check in dry_run without calling order_send.

## Acceptance criteria

- [ ] MT5 initialize, reconnect, account info, symbol info, spread, and tick fetch are implemented behind a narrow MT5 boundary.
- [ ] EURUSD M15 Closed Bars can be fetched from a demo terminal.
- [ ] The preflight refuses to use the Running Bar.
- [ ] A synthetic approved decision can be converted into an order_check request.
- [ ] order_check retcode, request hash, spread, magic, and comment are logged in the Audit Trail.
- [ ] The preflight proves order_send is not called in dry_run.

## Blocked by

- Bootstrap dry_run skeleton with audit trail.
- Run baseline Forecast through a fixture tick.

