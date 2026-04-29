---
title: Reconcile broker and local trade state after startup or timeout
labels: [needs-triage]
type: HITL
---

## What to build

Add Reconciliation for startup and order timeout scenarios. The system should compare broker positions identified by magic/comment with local trade records, detect mismatches, avoid automatic retry after order_send timeout, and emit alerts or audit records for operator review.

## Acceptance criteria

- [ ] Local trade state can be compared with broker positions by magic and structured comment.
- [ ] Broker positions missing locally are flagged as unmanaged.
- [ ] Local open trades missing at the broker trigger history lookup or operator alert.
- [ ] order_send timeout behavior does not automatically retry.
- [ ] Reconciliation results are written to the Audit Trail.
- [ ] Tests cover clean match, broker-only position, local-only trade, and timeout-before-persist scenarios.

## Blocked by

- Verify MT5 demo Closed Bar preflight and dry_run order_check.
- Enforce Risk Decision gate with sizing, SL/TP, and kill switch.

