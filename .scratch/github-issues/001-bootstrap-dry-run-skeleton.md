---
title: Bootstrap dry_run skeleton with audit trail
labels: [needs-triage]
type: AFK
---

## What to build

Create the first runnable skeleton for the AI MT5 multi-model trading system. A single command should load validated config, run one dry_run tick against fixtures, emit a trace ID, write structured logs, and persist an append-only Audit Trail record without touching MT5 or any live broker.

## Acceptance criteria

- [ ] A project entrypoint can run one dry_run tick locally.
- [ ] Config validation fails fast for missing required mode, symbol-timeframe, storage, risk, and execution settings.
- [ ] The tick creates a trace ID and propagates it into logs and audit output.
- [ ] Structured JSON logs are written for tick start, tick success, and tick failure.
- [ ] An append-only Audit Trail record is persisted for the tick.
- [ ] Tests cover config validation, trace ID propagation, and audit record creation.

## Blocked by

None - can start immediately.

