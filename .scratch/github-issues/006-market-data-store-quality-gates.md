---
title: Backfill market data store with quality gates
labels: [needs-triage]
type: AFK
---

## What to build

Create the local market data store and quality gate path for a Symbol-Timeframe. The slice should backfill or ingest bars, persist them in local storage, validate UTC alignment and continuity, flag spread and volume anomalies, and expose data freshness for downstream Forecast and backtest work.

## Acceptance criteria

- [ ] Bars are stored with symbol, timeframe, UTC timestamp, OHLCV, and spread fields.
- [ ] Storage supports deterministic replay for a configured Symbol-Timeframe.
- [ ] Data quality checks flag missing bars, abnormal spread, zero volume, and outlier returns.
- [ ] Freshness status is available to the tick runner and health output.
- [ ] Core bar data failure blocks trading; optional external data failure degrades safely.
- [ ] Tests cover storage round trip, continuity checks, timestamp alignment, and anomaly detection.

## Blocked by

- Run baseline Forecast through a fixture tick.

