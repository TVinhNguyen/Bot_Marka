# ADR 0009 — Observability, governance, and optional Agent Layer parity

Status: accepted
Issue: [#12](https://github.com/TVinhNguyen/Bot_Marka/issues/12)
Depends on: ADR 0004 (audit JSONL), ADR 0005 (data store), ADR 0007 (sizing)

## Context

The straight pipeline (`TickRunner` → `RiskManager`) is the source of truth.
Operators need:

1. A **live health surface** that says "is this safe to trade right now?"
2. **Metrics** that count what the pipeline did and how slow it was.
3. **Alerts** with severity and dedupe so flapping signals don't drown the operator.
4. **Daily / weekly reports** assembled from the persisted audit trail.
5. **Secret masking** so audit / log payloads never leak credentials.
6. **Audit hash chaining** so any post-hoc tampering is detectable.
7. An **optional Agent Layer** that can orchestrate the deterministic
   modules without changing decisions, with a strict tool allowlist that
   excludes `order_send` and risk-config mutation.

Issue #11 (MT5 connection state, last broker tick age) is deferred until the
real terminal client lands; the offline parts above can — and must — ship now.

## Decision

### Observability slice (`ai_mt5/observability/`)

- **`metrics.py`** — in-process `MetricsRegistry` with three kinds:
  counter, gauge, streaming histogram. Single lock for thread-safety.
  Canonical metric names (`forecasts_emitted`, `meta_signals_emitted`,
  `risk_decisions{outcome}`, `errors{kind}`, `spread_points`,
  `tick_latency_ms`, `open_positions`, `equity`, `drawdown_pct`,
  `kill_switch_events`, `data_freshness_lag_bars`) live in this module
  so tick code, agent layer, and tests share one source of truth.
  `register_default_metrics()` pre-registers them so snapshots always
  surface zeros for never-fired metrics.

- **`alerts.py`** — `AlertRule` is a pure
  `(payload) -> (key, message) | None`. `AlertManager` evaluates rules
  against payloads, deduplicates by `(rule_id, key)` over a configurable
  `cooldown`, fans out to subscribers, and keeps a fired-history for
  inspection. Severity is `warning | error | critical`. Default rules:
  `data_expired`, `kill_switch_engaged`, `drawdown_breach`,
  `adapter_failure_rate`.

- **`health.py`** — `build_health()` reads the audit trail, store, kill
  switch, and adapter list to produce a single JSON-serialisable
  `HealthSnapshot`. The MT5 piece is plugged in via an
  `MT5StatusProvider` Protocol; the default `DisconnectedMT5Status`
  reports `connected=False` so issue #11 can ship the real
  implementation behind the same interface.

- **`report.py`** — `build_period_report(records, window_start, window_end)`
  aggregates audit JSONL into an `OperationsReport` with per-kind
  counters (ticks success/fail, forecasts, meta-signals, approve/reject
  decisions, top rejection reasons, adapter failures, error kinds,
  distinct trace IDs). `to_dict()` for JSON, `to_markdown()` for human
  consumption.

- **`masking.py`** — `mask_secrets()` walks dict / list / tuple trees and
  replaces values whose key (case-insensitive) is in
  `SECRET_FIELD_NAMES` with `***`. Called from anywhere a payload leaves
  the process. Operates on a deep copy; never mutates.

- **`chain.py`** — `HashChainedAuditTrail` is a drop-in replacement for
  `JsonlAuditTrail` that adds `prev_hash` + `record_hash` (sha256) to
  every record. `verify_chain()` walks the file forward, recomputes
  every link, and reports the first mismatch. Tampering anywhere in the
  history is detectable in O(n).

### Agent Layer (`ai_mt5/agent/`)

- **`tools.py`** — `AgentToolset` is the *only* surface the agent may
  call. `AGENT_TOOL_ALLOWLIST` is a `frozenset` enforced at import time
  and at every dispatch. Forbidden names (`order_send`,
  `modify_risk_config`, `engage_kill_switch`, …) are asserted absent at
  module load. Calling anything outside the allowlist raises
  `DenyMutationError`.

- **`narration.py`** — `AgentNarration` (Pydantic v2) is a strict schema.
  `direction` is constrained to `BUY|SELL|HOLD`. `rationale` is rejected
  if it contains executor or credential tokens (`order_send`, `magic =`,
  `volume =`, `kill_switch = false`, `api[_- ]?key`, `password`).
  `validate_narration()` raises `NarrationValidationError`.

- **`layer.py`** — `AgentLayer.run_tick()` orchestrates the toolset in
  the same order as `TickRunner` and returns the *deterministic*
  `MetaSignal` and `RiskDecision`. The agent's only output is the
  narration; if its narration is missing, invalid, or disagrees with
  the deterministic decision, the layer falls back to a built-in
  deterministic narration and records `narration_fallback`. This is
  asserted by `test_agent_path_matches_straight_pipeline` and
  `test_agent_falls_back_when_narrator_disagrees`.

### CLI surface

- `ai-mt5 health` — JSON snapshot, exit 1 when status is `unhealthy`.
- `ai-mt5 report --days N --format json|markdown [--out PATH]` —
  daily/weekly aggregates from the audit trail.

### TickRunner integration

`TickRunner` now exposes `metrics` and `alerts` properties. Per tick it:

1. Increments `FORECASTS_EMITTED`, `META_SIGNALS_EMITTED`,
   `RISK_DECISIONS{outcome=...}`, `ERRORS{kind=...}` (on failure).
2. Sets `SPREAD_POINTS` and `DATA_FRESHNESS_LAG_BARS` gauges.
3. Observes `tick_latency_ms` for both success and failure paths.
4. Evaluates the alert manager with `freshness`, `kill_switch_engaged`,
   `adapter_failure_rate` — defaults plus operator extensions.

## Consequences

- Operators get JSON health, JSON / Markdown reports, and a live metrics
  registry without any new infrastructure dependencies.
- Audit tampering is detectable; live logs are safe to ship.
- The Agent Layer is provably non-decisive — replay parity is asserted.
- MT5 status is the only deferred piece; #11 plugs into the existing
  `MT5StatusProvider` Protocol with no further surgery on the health code.

## Alternatives considered

- **Prometheus / OpenTelemetry SDK directly inside `TickRunner`.**
  Rejected for now: pulls in a heavy dependency and a network surface.
  The in-process registry's `to_dict()` ships easily to either when
  needed.
- **Letting the agent return a separate decision and reconciling.**
  Rejected: any divergence from the deterministic decision must be
  treated as a bug in the agent, not as an alternative trade. The layer
  enforces this by *only* surfacing the deterministic decision and
  treating divergent narration as a fallback signal.
- **Storing the audit hash chain as a separate file.** Rejected: keeps
  the JSONL self-describing and makes verification trivial without
  cross-file lookups.
