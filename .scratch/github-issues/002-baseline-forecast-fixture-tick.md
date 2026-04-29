---
title: Run baseline Forecast through a fixture tick
labels: [needs-triage]
type: AFK
---

## What to build

Run an end-to-end fixture tick that loads Closed Bars from local test data, builds anti-leak features, produces a Baseline Forecast, records it through the same storage and Audit Trail used by the dry_run skeleton, and ends in HOLD without MT5 access.

## Acceptance criteria

- [ ] Fixture OHLCV data is loaded as Closed Bars only.
- [ ] Feature generation uses only data available before the decision bar.
- [ ] The Baseline produces a Forecast using the shared forecast contract.
- [ ] Forecast and tick audit records are persisted and queryable.
- [ ] Missing or invalid fixture data fails with a structured error.
- [ ] Tests prove no Running Bar is used and no future value leaks into features.

## Blocked by

- Bootstrap dry_run skeleton with audit trail.

