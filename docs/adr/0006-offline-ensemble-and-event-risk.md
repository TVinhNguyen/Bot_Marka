# ADR 0006 — Offline Model Adapters, Event Risk, and Ensemble

* **Status**: Accepted
* **Issues**: #7, #8, #9
* **Depends on**: ADR 0005 (bar store and quality gates)

## Context

The dry-run skeleton ships with a single Baseline adapter. The domain
language in [`CONTEXT.md`](../../CONTEXT.md) separates four deterministic
roles:

* **Model Adapter** — produces a `Forecast`;
* **Ensemble** — combines Forecasts into a single `MetaSignal`;
* **Risk Decision** — turns an actionable `MetaSignal` into a sized SL/TP
  decision (or a rejection);
* **Executor** — validates and submits broker requests.

Issues #7–#9 ask for an evaluable, offline version of the first two
boxes — without any live MT5 or LLM dependency. The outputs must keep
the same contract that future production adapters (real TimesFM /
Kronos / Chronos weights, a hosted LLM for news) will honour.

## Decision

### Model Adapters (`src/ai_mt5/models/`)

* A single `ModelAdapter` `Protocol` with `name`, `version`, and
  `forecast(features, *, symbol, timeframe) -> Forecast`.
* Three offline mocks — `TimesFMAdapter`, `KronosAdapter`,
  `ChronosAdapter` — each deterministic and driven only by the shared
  `FeatureSet`.
* Every Forecast embeds an `input_hash` (SHA-256 of the serialized
  features), the pinned `model_version`, and the declared `horizon`.
  Persistence and re-evaluation are therefore reproducible by
  construction.
* Failures are raised as `AdapterError`. The Ensemble records failures
  as a rate and can veto on that rate alone.
* `evaluate_adapter(adapter, bars, *, cost_per_trade, min_history)`
  walks the fixture forward, runs the adapter without look-ahead, and
  emits an `EvaluationReport` with direction accuracy, edge after cost,
  mean uncertainty, and explicit `limitations` tags.

### Event Risk (`src/ai_mt5/text/`)

* `NewsStore` — append-only JSONL of `NewsEvent(symbol, scheduled_at,
  impact, title, source, relevance, tags)`. `retrieve()` filters by
  symbol, a past-recency window, and a bounded future window so
  scheduled releases can be seen without leaking post-event prices.
* `EventRiskAdapter.evaluate(symbol, as_of) -> EventRiskOutput`. The
  adapter degrades to a conservative output when news is missing
  (`no_news_for_symbol`), stale beyond a configurable
  `stale_after` (`stale_news_latest=...`), or simply absent from the
  retrieval window (`no_news_in_window` — low risk, permit).
* Guardrails:
  * `sanitize_news_text()` strips any token on the forbidden action list
    (`order_send`, `set risk`, `magic=`, `volume=`, ...).
  * `validate_event_risk()` refuses outputs that are out of range,
    non-finite, or carry forbidden tokens in metadata — so a poisoned
    fixture can't reach the persistence layer.
  * Any news item that contains a forbidden token contributes **zero**
    sentiment, so the ensemble cannot be nudged by an injection.
* `JsonlEventRiskStore` — append-only persistence with
  source-metadata fields, `fsync` on each line.

### Ensemble (`src/ai_mt5/ensemble/`)

* `Ensemble.combine(forecasts, *, event_risk, spread_points,
  n_adapter_failures, n_adapter_total)` is the single deterministic
  entrypoint.
* Validation rejects non-finite Forecasts. Weights are rescaled over
  the adapters that actually produced output so missing adapters reduce
  to the active set.
* `MetaSignal` records raw score, cost penalty, uncertainty penalty,
  Event Risk penalty, final score, agreement, and the full component
  Forecast map for audit.
* Hard vetoes returning `HOLD` (in the `veto_reasons` list):
  `insufficient_models`, `low_agreement`, `excessive_spread`,
  `high_event_risk`, `event_risk_no_permission`,
  `adapter_failure_rate`, `zero_final_score`.
* **No sizing, no SL/TP, no broker call.** Those remain the Risk
  Manager's and Executor's responsibilities.

### TickRunner wiring

`TickRunner.__init__` now takes `adapters`, `ensemble`, and optional
`event_risk`. When wired:

1. Baseline forecast runs first.
2. Each configured Model Adapter runs; errors are audited as
   `adapter_failure` and counted as failures.
3. Event Risk (if configured) runs once per decision bar and is
   audited as `event_risk`.
4. The Ensemble combines all valid forecasts and Event Risk into a
   `MetaSignal`. The resulting veto list is passed to the Risk gate.

## Consequences

* Every component of the Forecast → MetaSignal → Risk Decision pipe is
  now exercised by tests, including prompt-injection refusal.
* The Ensemble can be evolved (e.g. regime gating, correlation haircut)
  without touching adapter code.
* Real model weights slot in behind the same `ModelAdapter` Protocol;
  the existing tests will catch contract drift.
* Persisted Forecasts carry a stable `input_hash`, enabling walk-forward
  replay (#10) to re-derive ensemble decisions deterministically.

## Non-goals

* No real LLM calls, model weights, or live news.
* No sizing or execution changes — the Risk Decision stage is unchanged.
