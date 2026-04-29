---
title: PRD 003 - Offline Model Adapters and Forecast Evaluation
labels: [needs-triage]
status: draft
created: 2026-04-29
source_docs: [03-tech-stack.md, 04-models.md, 05-data-pipeline.md, 06-meta-signal.md, 10-backtesting.md, 12-config.md, 13-roadmap.md, 16-testing-qa.md, 18-pitfalls.md, 19-references.md]
---

# PRD 003 - Offline Model Adapters and Forecast Evaluation

## Problem Statement

The project depends on multiple forecasting models, but integrating them directly into execution would create safety, latency, and reproducibility risks. Each model has different input requirements, output shapes, confidence semantics, dependencies, and failure modes.

The user needs each model adapter to run offline first, conform to one forecast contract, persist predictions, and produce evaluation reports before any adapter is allowed into the execution loop.

## Solution

Build offline adapters for TimesFM, Kronos, Chronos, FinGPT/RAG, and baseline controls. Each adapter must return a normalized forecast with direction, expected return, uncertainty, score, confidence, horizon, reason, and metadata. Each adapter will be evaluated on historical data and stored predictions before being eligible for ensemble backtests.

The adapter layer will isolate model-specific logic, dependency loading, input preparation, score normalization, and failure handling behind stable interfaces. Model failures must be explicit and auditable, and more than 50% adapter failure must later force the ensemble to HOLD.

## User Stories

1. As an ML engineer, I want a shared model forecast contract, so that ensemble logic can consume all model outputs uniformly.
2. As an ML engineer, I want TimesFM to forecast log-return, volatility, or ATR-normalized targets, so that generic time-series signals can be evaluated.
3. As an ML engineer, I want TimesFM outputs normalized into a bounded score, so that the model cannot dominate the ensemble by scale alone.
4. As an ML engineer, I want Kronos to forecast OHLCV/K-line structure, so that the system can capture financial candle patterns.
5. As an ML engineer, I want Kronos commit and checkpoint versions pinned, so that forecast reports are reproducible.
6. As an ML engineer, I want Kronos direction probability calibrated, so that confidence is meaningful rather than raw model enthusiasm.
7. As an ML engineer, I want Chronos to produce quantile forecasts, so that uncertainty and skew can be measured independently from TimesFM and Kronos.
8. As an ML engineer, I want Chronos covariates to be optional and timestamp-aligned, so that cross-asset features do not leak future information.
9. As an ML engineer, I want FinGPT or FinBERT to produce sentiment, event risk, summaries, and trade permission hints, so that news can reduce or block trades.
10. As an ML engineer, I want RAG retrieval to filter by symbol, timestamp, recency, and relevance, so that stale or unrelated news does not drive decisions.
11. As a quant lead, I want each adapter evaluated independently against baseline and cost assumptions, so that weak adapters are identified before ensemble use.
12. As a quant lead, I want per-model direction accuracy, edge after cost, Brier score where relevant, and calibration metrics, so that adapter quality is measurable.
13. As a quant lead, I want forecast correlation between models measured, so that agreement is not mistaken for independent evidence.
14. As a quant lead, I want reports to say clearly when an adapter has no positive edge, so that losing models are not hidden inside the ensemble.
15. As a backend engineer, I want adapters to accept prepared data instead of fetching from MT5 directly, so that inference is decoupled from data I/O.
16. As a backend engineer, I want adapters to fail with structured errors, so that failures can be logged and handled deterministically.
17. As a backend engineer, I want adapter output saved to prediction storage, so that later ensemble experiments can replay forecasts without rerunning expensive models.
18. As a reviewer, I want metadata to include context length, horizon, target, checkpoint, and input hash, so that each forecast can be audited.
19. As a security reviewer, I want model dependencies pinned, so that supply-chain and reproducibility risks are reduced.
20. As a QA engineer, I want adapter contract tests, so that no adapter can merge unless it returns valid schema fields.
21. As a QA engineer, I want smoke tests for each adapter, so that CI catches missing dependencies or broken output parsing.
22. As an operator, I want missing news to degrade sentiment weight rather than crash the pipeline, so that text intelligence remains optional until proven stable.

## Implementation Decisions

- Build adapters offline first and keep them out of the execution loop until PRD 004 validates ensemble behavior.
- Treat the model contract and adapter base interface as deep modules.
- Normalize every adapter score into the same bounded range.
- Keep score normalization model-specific but make the output contract model-agnostic.
- Use the baseline adapter as the control and schema reference.
- Persist raw model metadata needed for audit and reproducibility.
- Store predictions per model, symbol, timeframe, horizon, and run configuration.
- Make adapter dependencies optional where feasible so that one disabled model does not block the full project.
- Pin major/minor package versions and pin external git model dependencies by commit.
- Enforce deterministic seeds where model libraries support it.
- Treat FinGPT/RAG as an event-risk and sentiment module, not as an execution decision maker.
- Use conservative defaults when sentiment data is stale, missing, or retrieval confidence is low.
- Do not allow any adapter to import or call execution or risk mutation behavior.

## Testing Decisions

- Good adapter tests verify the public forecast contract, NaN handling, timestamp alignment, and failure behavior.
- Unit test each adapter normalizer with representative outputs and boundary values.
- Unit test missing-column and short-history behavior for each adapter.
- Unit test FinGPT/RAG retrieval filtering for recency, symbol relevance, and timestamp strictness.
- Smoke test each adapter with a small fixture and assert a valid forecast object.
- Heavy tests should run offline or nightly on at least one month of data.
- Evaluation reports should include out-of-sample metrics and note whether the adapter beats naive or baseline references after costs.
- Regression tests should compare stored predictions for fixed fixtures when model determinism allows it.

## Out of Scope

- Live execution.
- Ensemble weight tuning.
- Automatic retraining.
- Model serving infrastructure.
- Multi-symbol production rollout.
- Agent-based model routing.

## Further Notes

Adapters that cannot produce the shared forecast contract should not be merged into ensemble experiments. Offline failure is cheaper than live ambiguity.

