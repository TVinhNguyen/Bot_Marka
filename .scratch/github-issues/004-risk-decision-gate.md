---
title: Enforce Risk Decision gate with sizing, SL/TP, and kill switch
labels: [needs-triage]
type: AFK
---

## What to build

Implement the Risk Decision gate as a deterministic module that approves or rejects a Meta-Signal using fixture account and market snapshots. It should calculate position size, SL, TP, margin checks, spread checks, daily/drawdown limits, news windows, and kill switch behavior before anything can reach the Executor.

## Acceptance criteria

- [ ] Risk evaluation returns an explicit approve or reject decision with reasons.
- [ ] Approved decisions include side, volume, SL, TP, magic, and comment.
- [ ] Rejected decisions include all applicable rejection reasons.
- [ ] Position sizing respects broker min/max/step and max risk caps.
- [ ] SL/TP respects ATR, risk-reward, and broker stop-level constraints.
- [ ] Manual kill switch forces new decisions to reject until explicitly cleared.
- [ ] Unit and property tests cover hard limits, sizing invariants, news window, spread limits, margin insufficiency, and kill switch behavior.

## Blocked by

- Bootstrap dry_run skeleton with audit trail.

