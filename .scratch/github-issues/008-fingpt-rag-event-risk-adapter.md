---
title: Evaluate FinGPT/RAG Event Risk adapter offline
labels: [needs-triage]
type: AFK
---

## What to build

Build the offline text-intelligence adapter that retrieves recent news context, scores sentiment and Event Risk, degrades safely when news is stale or missing, and proves LLM output cannot submit orders or mutate risk settings.

## Acceptance criteria

- [ ] News fixtures can be retrieved by symbol, timestamp, recency, and relevance.
- [ ] The adapter produces a shared Forecast-compatible output for sentiment, Event Risk, direction bias, trade permission, and metadata.
- [ ] Stale or missing news degrades to conservative Event Risk behavior without crashing the pipeline.
- [ ] Prompt-injection fixtures cannot cause order submission, risk config mutation, or free-form numeric overrides.
- [ ] Adapter outputs are schema-validated and persisted with source metadata.
- [ ] Tests cover timestamp filtering, stale news, missing news, schema validation, and refusal behavior.

## Blocked by

- Backfill market data store with quality gates.

