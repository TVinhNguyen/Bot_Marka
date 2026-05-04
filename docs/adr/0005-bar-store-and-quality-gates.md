# ADR 0005 — Local bar store and market-data quality gates

Status: Accepted (issue #6 implementation)
Date: 2026-04-30

## Context

Issue #6 asks for a local market-data store that can be replayed
deterministically, plus a set of quality gates that detect data problems
before they reach the forecast and risk pipeline. The downstream slices
(model adapters #7, event-risk adapter #8, ensemble #9, backtest #10) all
read bars from this store, so its contract has to be stable before those
slices can begin.

## Decision

### Storage format: per-(symbol, timeframe) JSONL

* One file per `{symbol}_{timeframe}.jsonl` under `storage.bars_path`.
* One Closed Bar per line, JSON-encoded, keys sorted for stable diffs.
* Append-only writes through `BarStore.append_many`, which:
  * rejects mixed-symbol / mixed-timeframe batches,
  * de-dupes against already-stored `open_time`s (idempotent ingest),
  * `fsync`s after every flush for durability.

JSONL matches the audit trail (ADR 0004) and can be swapped for Parquet /
DuckDB later without changing the `BarStore` public surface.

### Freshness as a first-class concept

`BarStore.freshness` returns a `FreshnessStatus` with four states:
`FRESH`, `STALE`, `EXPIRED`, `EMPTY`. Thresholds are expressed in *units
of bar length* for the configured timeframe so M1 and H4 use the same
configuration variables. The tick runner blocks trading when the state
is `EXPIRED` and `data_quality.block_tick_on_expired` is `true`.

### Core vs. optional quality checks

Per the issue brief, core bar data failure must block trading while
optional external-data failure must degrade safely. We split the checks
the same way inside `run_quality_gates`:

| Check                        | Severity  |
| ---------------------------- | --------- |
| Naive / non-UTC timestamps   | Blocking  |
| Non-monotonic timestamps     | Blocking  |
| Missing bars (gap > tol)     | Blocking  |
| Short gaps / misalignment    | Blocking  |
| Empty series                 | Blocking  |
| Zero volume                  | Warning   |
| Abnormal spread              | Warning   |
| Outlier returns (MAD-based)  | Warning   |

The return-outlier check uses a robust MAD multiple of the absolute
returns instead of a mean/stdev rule so a single jumbo move doesn't
also suppress its own detection.

### Configuration

Thresholds live in `AppConfig.data_quality` (`DataQualityConfig`) so
they are validated and documented like every other tunable. They are
also reachable from every consumer (tick runner, ingest helpers,
future backfill jobs) through the same `AppConfig` instance.

### Audit coverage

Every tick now emits `data_quality` and `data_freshness` records in
addition to the existing `tick.start` / `forecast` / `meta_signal` /
`risk_decision` / `tick.success|failure` events. Audit readers can now
answer "why did this tick refuse to trade?" without re-reading market
data.

### Health output and replay-from-store

The store exposes a structured `BarStore.health(symbol, timeframe, now)`
that returns `StoreHealth` (bar count, earliest/latest `open_time`,
filesystem `last_modified`, freshness state). The CLI subcommand
`ai-mt5 store-health` prints the same payload as JSON so operators have
a one-line probe without writing Python. The same payload will back any
future HTTP/Prometheus health endpoint without re-deriving the math.

`ai-mt5 dry-run-tick` also gains a `--from-store` flag that loads bars
from the local `BarStore` instead of the CSV fixture, making the store
the deterministic replay source. When both `--bars` and `--from-store`
are supplied, the CSV is ingested into the store first (idempotent) and
the tick replay then reads from the store. This satisfies issue #6's
"replay-from-store path" acceptance criterion while preserving the
fixture-only smoke path for tests that don't need persistence.

## Consequences

* Backtests (#10) and the model adapters (#7) will consume `BarStore`
  as the canonical source, so their tests can fixture a few bars into a
  `tmp_path` store instead of faking an MT5 client.
* Moving to Parquet or DuckDB later only requires re-implementing
  `BarStore`; the quality / freshness / audit contracts are unaffected.
* The fixture-CSV loader (`load_closed_bars_csv`) stays around for the
  dry-run smoke path but is no longer on the production tick path.
