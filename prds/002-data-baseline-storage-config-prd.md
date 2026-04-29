---
title: PRD 002 - Data Pipeline, Storage, Baseline, and Configuration
labels: [needs-triage]
status: draft
created: 2026-04-29
source_docs: [01-overview.md, 03-tech-stack.md, 05-data-pipeline.md, 11-project-structure.md, 12-config.md, 13-roadmap.md, 15-monitoring.md, 16-testing-qa.md, 18-pitfalls.md]
---

# PRD 002 - Data Pipeline, Storage, Baseline, and Configuration

## Problem Statement

The system needs reliable data, reproducible configuration, baseline signals, and persistent logs before advanced AI adapters are useful. If data freshness, feature alignment, storage schemas, and config validation are weak, backtests and live decisions will be misleading and unsafe.

The user needs a deterministic data and baseline layer that can run end-to-end with no AI dependency, prove the trading loop is auditable, and provide a control strategy for comparing the later ensemble.

## Solution

Build the data pipeline around closed-bar market data, strict anti-leak feature engineering, configurable symbol selection, local-first storage, prediction logs, and a baseline adapter. The MVP will use Parquet or DuckDB for bars, SQLite for forecasts/signals/trades, and structured logs or CSVs for operator inspection.

The baseline strategy will produce the same forecast contract as AI adapters, allowing the ensemble and storage layers to be tested before TimesFM, Kronos, Chronos, or FinGPT are added.

## User Stories

1. As a quant lead, I want a single primary symbol and timeframe enabled first, so that the MVP can prove stability before expansion.
2. As a quant lead, I want OHLCV bars fetched from MT5 and stored locally, so that backtests and replay use the same raw market data.
3. As a quant lead, I want every bar stored with UTC timestamps, so that cross-source alignment is consistent.
4. As a quant lead, I want features based only on data available before the decision bar, so that look-ahead bias is prevented.
5. As a quant lead, I want return, log-return, ATR, realized volatility, volume z-score, and spread normalization, so that model inputs are comparable across symbols.
6. As a quant lead, I want baseline SMA/ATR and baseline ML control outputs, so that AI performance can be measured against simple strategies.
7. As an ML engineer, I want feature engineering to operate on dataframes without direct MT5 access, so that offline evaluation and live replay use the same logic.
8. As an ML engineer, I want cross-asset features to be timestamp-aligned, so that Chronos covariates do not introduce leakage.
9. As an ML engineer, I want missing bars, abnormal spread, zero volume, and outlier returns flagged, so that bad data can degrade or halt trading safely.
10. As a backend engineer, I want a storage layer for bars, forecasts, signals, trades, and audit metadata, so that every decision can be replayed.
11. As a backend engineer, I want prediction and signal records to share stable schemas, so that later adapters can plug into the same pipeline.
12. As a backend engineer, I want config-driven environments, symbols, risk, model weights, execution, and monitoring, so that behavior changes through reviewed configuration rather than code edits.
13. As a backend engineer, I want config validation at startup, so that invalid risk or execution settings fail fast.
14. As a backend engineer, I want config load order to support base config, environment overrides, and CLI overrides, so that dev, dry_run, demo, and live can share structure safely.
15. As a security reviewer, I want secrets kept out of YAML and logs, so that MT5 credentials and API keys do not leak.
16. As an operator, I want append-only signal and trade CSVs in MVP, so that decisions can be inspected without a dashboard.
17. As an operator, I want data freshness SLOs and warnings, so that stale market or news data does not silently drive decisions.
18. As an operator, I want fallback behavior when external sources fail, so that missing news or cross-asset data does not crash the core pipeline.
19. As a reviewer, I want baseline forecasts saved like model forecasts, so that downstream audit and reports do not need special cases.
20. As a QA engineer, I want fixture data for bars, news, account snapshots, broker costs, and ensemble cases, so that repeatable tests can run in CI.
21. As a QA engineer, I want a dry_run E2E pipeline with baseline only, so that data, storage, signal, risk, and executor integration work before AI models.

## Implementation Decisions

- Use Python 3.11+ as the core runtime.
- Use local-first storage for MVP: Parquet or DuckDB for market bars and SQLite for forecast, signal, and trade records.
- Keep Postgres and TimescaleDB as the production path once the system needs multi-host deployment or stronger query guarantees.
- Treat feature building as a deep module with a dataframe-in, dataframe-out interface.
- Treat storage as a deep module with explicit methods for bars, forecasts, signals, risk decisions, trade attempts, and audit events.
- Implement baseline as a normal adapter that returns the same forecast contract as AI adapters.
- Make closed-bar-only behavior the default and enforce it in data loading and tests.
- Use UTC for storage and treat display timezone as presentation only.
- Add data quality checks as first-class pipeline outputs, not as ad hoc logging.
- Build config validation with typed schemas and fail startup on invalid values.
- Keep secrets in environment variables or a secret manager, never in config files.
- Disable hot reload for risk-related config in live mode.
- Log config diffs and alert on risk or execution config changes.
- Use graceful degradation for optional sources: missing news lowers sentiment availability, while missing core bars blocks trading.

## Testing Decisions

- Good tests assert external data behavior: no running candle, no look-ahead features, stable schema, correct timestamps, and correct degradation mode.
- Unit test feature calculations using deterministic small fixtures.
- Unit test data quality checks for missing bars, spread anomalies, zero volume, and outlier returns.
- Unit test config validation for valid configs, invalid risk bounds, missing secrets, and live-mode constraints.
- Unit test baseline adapter output contract and NaN-safe behavior.
- Integration test storage round trips for bars, forecasts, signals, risk decisions, and trades.
- E2E dry_run test should run the baseline-only pipeline and assert that signal and audit records are created.
- Daily data tests should check bar continuity, spread median, volume sanity, news document count, and embedding count once news ingestion exists.

## Out of Scope

- Training or running advanced AI adapters.
- Full production database migration strategy.
- Real-time tick microstructure strategy.
- News RAG inference beyond ingestion scaffolding.
- Live order_send.
- Agent orchestration.

## Further Notes

This PRD creates the control surface that all later model and ensemble work depends on. The baseline is not expected to be profitable; it is a reference point for validating whether the AI ensemble adds real value after cost.

