---
title: Add observability, governance, and optional Agent Layer parity
labels: [needs-triage]
type: AFK
---

## What to build

Add the first complete observability and governance slice, then prove the optional Agent Layer can orchestrate the same deterministic modules without changing decisions. The straight pipeline remains the source of truth; agents may only coordinate and produce Audit Narration.

## Acceptance criteria

- [ ] Health output exposes MT5 connection state, last tick age, open positions, kill switch state, data freshness, and model status.
- [ ] Metrics cover forecasts, Meta-Signals, Risk Decisions, errors, spread, latency, open positions, equity, drawdown, and kill switch events.
- [ ] Alert severity and dedupe rules exist for warnings, errors, and critical incidents.
- [ ] Daily or weekly report generation reads from persisted audit records.
- [ ] Secret masking and audit hash chaining are implemented or stubbed behind testable interfaces.
- [ ] Agent tool allowlists exclude order_send and risk config mutation.
- [ ] Agent outputs are schema-validated and can fall back to deterministic behavior.
- [ ] Replay tests prove the Agent Layer path matches the straight pipeline for the same inputs.

## Blocked by

- Produce auditable Meta-Signal from stored Forecasts.
- Operate Shadow Mode and promotion gates.

