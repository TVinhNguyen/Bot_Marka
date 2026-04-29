---
title: Evaluate time-series Model Adapters offline
labels: [needs-triage]
type: AFK
---

## What to build

Build offline Model Adapter evaluation for TimesFM, Kronos, and Chronos using stored Closed Bars. Each adapter should produce the shared Forecast contract, persist predictions, record reproducibility metadata, and generate evaluation metrics without entering the live execution loop.

## Acceptance criteria

- [ ] TimesFM adapter can produce normalized Forecasts for configured return or volatility targets.
- [ ] Kronos adapter can produce normalized Forecasts with pinned model version metadata.
- [ ] Chronos adapter can produce quantile Forecasts with uncertainty fields.
- [ ] Each adapter persists predictions with symbol-timeframe, horizon, config, input hash, and model metadata.
- [ ] Evaluation reports include direction accuracy, edge after cost where applicable, uncertainty/calibration metrics, and known limitations.
- [ ] Contract tests reject invalid Forecast outputs.
- [ ] Adapter failures are structured and auditable.

## Blocked by

- Backfill market data store with quality gates.

