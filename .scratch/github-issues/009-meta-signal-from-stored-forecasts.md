---
title: Produce auditable Meta-Signal from stored Forecasts
labels: [needs-triage]
type: AFK
---

## What to build

Combine stored Forecasts into an auditable Meta-Signal. The Ensemble should validate forecasts, rescale active weights, calculate agreement, costs, uncertainty and Event Risk penalties, apply hard vetoes, and persist the resulting BUY, SELL, or HOLD decision without sizing or execution.

## Acceptance criteria

- [ ] Forecast validation excludes invalid or NaN outputs.
- [ ] Weights rescale when optional models are unavailable.
- [ ] Agreement, raw score, cost penalty, uncertainty penalty, Event Risk penalty, final score, confidence, and veto reasons are recorded.
- [ ] Hard vetoes return HOLD for high Event Risk, excessive spread, low agreement, insufficient models, and adapter failure thresholds.
- [ ] Meta-Signal output includes the original component Forecasts for audit.
- [ ] Tests cover weight rescaling, penalties, thresholds, each veto, and HOLD behavior under missing or invalid Forecasts.

## Blocked by

- Evaluate time-series Model Adapters offline.
- Evaluate FinGPT/RAG Event Risk adapter offline.

