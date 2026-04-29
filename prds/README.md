---
title: PRD Index - AI MT5 Multi-Model Trading System
labels: [needs-triage]
created: 2026-04-29
source_docs:
  - README.md
  - 01-overview.md
  - 02-architecture.md
  - 03-tech-stack.md
  - 04-models.md
  - 05-data-pipeline.md
  - 06-meta-signal.md
  - 07-risk-management.md
  - 08-mt5-execution.md
  - 09-agents.md
  - 10-backtesting.md
  - 11-project-structure.md
  - 12-config.md
  - 13-roadmap.md
  - 14-deployment.md
  - 15-monitoring.md
  - 16-testing-qa.md
  - 17-security.md
  - 18-pitfalls.md
  - 19-references.md
---

# PRD Index

## Review Summary

The Markdown documentation describes a blueprint-stage AI MT5 multi-model trading system. The key domain rules are consistent across the docs:

- Model adapters only produce forecasts and normalized scores.
- The meta-signal engine combines forecasts but does not size or execute trades.
- The risk manager is the hard approval gate and cannot be bypassed.
- The MT5 executor is the only component allowed to submit orders.
- Live deployment must progress through dry_run, demo, staging, and small live size.
- Every forecast, signal, risk decision, order check, and order result must be auditable.

The roadmap is best converted into multiple PRDs rather than one large PRD, because each PRD can be implemented and tested independently.

## PRD Set

1. [MT5 Skeleton, Risk Gate, and Execution Safety](001-mt5-skeleton-risk-execution-prd.md)
2. [Data Pipeline, Storage, Baseline, and Configuration](002-data-baseline-storage-config-prd.md)
3. [Offline Model Adapters and Forecast Evaluation](003-offline-model-adapters-prd.md)
4. [Meta-Signal Engine and Walk-Forward Backtesting](004-ensemble-backtest-prd.md)
5. [Paper, Demo, Staging, and Small Live Deployment](005-demo-live-operations-prd.md)
6. [Agent Orchestration, Observability, Security, and Governance](006-agents-observability-security-prd.md)

## Cross-PRD Gate Order

1. Build MT5 dry_run skeleton before any live order flow.
2. Build deterministic data, baseline, storage, and config validation before model integration.
3. Run model adapters offline before putting them into the execution loop.
4. Prove ensemble edge with walk-forward out-of-sample backtests before demo trading.
5. Run shadow and demo for 2-4 weeks before live.
6. Add agent orchestration only after the deterministic pipeline is stable.

## Global Out of Scope

- High-frequency or sub-second trading.
- Autonomous LLM trading or LLM-controlled order submission.
- Automatic retraining loops.
- Production Kafka streaming.
- Multi-broker arbitrage.
- Advanced multi-account portfolio management.

