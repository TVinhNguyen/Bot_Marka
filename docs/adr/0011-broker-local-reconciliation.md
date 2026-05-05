# ADR 0011 — Broker / local trade-state reconciliation

## Status

Accepted (implements issue #5).

## Context

The bot will eventually call `order_send`. Network or terminal failure
between "I sent the request" and "I observed the result" is a normal
operating condition: the broker may have opened the position, may have
rejected it, or may simply not have received it. Without a reconciler,
the bot has no way to recover safely from this ambiguity — it will
either silently retry (double position) or silently abandon (orphan).

Issue #5 demands an explicit reconciliation step at startup and after
order timeout, with the following invariants:

* Local trade state can be compared to broker positions by `magic` and
  a structured `comment`.
* Broker positions belonging to our `magic` that the bot does not know
  about are flagged as **unmanaged**.
* Local trades the broker doesn't have trigger a history lookup or
  operator alert.
* `order_send` timeout never auto-retries.
* The reconciliation result is written to the audit trail.

## Decision

Introduce a small `ai_mt5/execution/` package containing:

1. **`LocalIntent`** dataclass (immutable) — the bot's belief about
   one trade: `intent_id`, `symbol`, `side`, `volume`, `magic`,
   `comment`, `state`, `ticket`, plus timestamps. State is one of
   `intended`, `submitted`, `timeout`, `closed`, `orphaned`. State
   transitions are append-only events in a JSONL log; "current state"
   is computed as the latest record per `intent_id`.
2. **`LocalIntentLog`** — JSONL on-disk ledger with `append`, `all_intents`,
   and `open_intents()` (latest-state filter, ignores `closed`).
3. **`BrokerPosition`** — broker-side row normalised from
   `MT5Client.positions()`.
4. **`reconcile()`** — pure function that compares two snapshots and
   returns a `ReconcileReport` with five buckets: `matched`,
   `broker_only` (unmanaged with our magic), `local_only` (orphaned),
   `timeout_pending` (no auto-retry), `foreign_positions` (other magic).
5. **CLI `ai-mt5 reconcile`** — connects via the bridge, fetches
   positions, runs `reconcile()`, appends a `reconcile.report` audit
   record, and prints JSON. Exit 1 if the report is not OK.

### Match strategy

The primary match key is `(magic, comment)`. `comment` is the
structured 31-char broker comment built by `structured_comment(magic,
intent_id)` so that the broker's view round-trips back to the local
intent without any shared state. When a local intent already carries a
ticket but the broker comment matches a *different* ticket, the
intent is reported as `local_only` and the broker row as
`broker_only` — the reconciler refuses to silently rebind.

### Timeout policy

If a local intent is in state `timeout`, the reconciler **always**
emits it as `timeout_pending`, regardless of whether the broker echoes
it. This makes "do not auto-retry" a property of the data flow, not a
runtime check that some future code path could forget.

### Foreign positions

Positions whose `magic` does not match ours are exposed in
`foreign_positions` for transparency but never trigger alerts. They
prevent the report from claiming "unmanaged" on, e.g., manual trades
or other bots running on the same account.

## Consequences

* Trade-intent persistence is independent of audit. The intent log is
  append-only and crash-safe (each record fsyncs).
* The reconciler is a pure function with no I/O — fully deterministic
  and testable without a broker. Live wiring is a thin CLI/runner
  shell that calls `MT5Client.positions()` and the reconciler.
* The "no auto-retry" guarantee is structural: there is no API on the
  reconciler that promotes a `timeout` intent. Promotion is a new
  append on the log driven explicitly by the operator.
* When `execution.reconcile_on_start` is `True`, callers integrating
  with the live runtime (next slice) will run `ai-mt5 reconcile`
  before the first tick and refuse to start if the report is not OK.

## Out of scope

* Live `order_send` (still pre-execution slice).
* Automatic history lookup for `local_only` intents — currently
  surfaced as alert-only, per the acceptance criterion's "history
  lookup OR operator alert" wording.
* TickRunner integration of `reconcile_on_start` — the field already
  exists in config; wiring lands together with the live executor.
