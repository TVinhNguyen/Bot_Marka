# ADR 0012 — Shadow Mode, runtime modes, and promotion gates

**Status:** Accepted
**Date:** 2026-04-29
**Issue:** #11

## Context

The bot can in principle reach a state where the model pipeline emits
plausible signals but the operational scaffolding (kill switch,
reconciliation, monitoring, rollback path) is not yet ready for live
trades. We need a hardened path between offline development
(``dry_run``) and production (``small_live``) that:

1. Runs the full pipeline against live data so we can observe its
   behaviour, while making it impossible for the executor to fire.
2. Captures enough metadata in the audit trail to compare model
   decisions with subsequent realised market behaviour.
3. Enforces a minimum operational baseline (tests passing, secrets
   present, kill switch reachable, recent backtest, known commit)
   before any promotion to demo or higher.
4. Provides a documented rollback that points at a specific commit +
   config snapshot.

## Decision

### Six-mode ladder

A single ``RuntimeMode`` enum (see ``src/ai_mt5/runtime/modes.py``)
defines the only allowed environments:

| Mode | Live data | order_send |
| ---- | --------- | ---------- |
| ``dev`` | no | no |
| ``dry_run`` | no (fixture replay) | no |
| ``shadow`` | yes | **no** |
| ``demo`` | yes | yes |
| ``staging`` | yes | yes |
| ``small_live`` | yes | yes (capped) |

The single source of truth for the executor gate is
``allows_order_send(mode)``. Any future mode MUST be added to that
predicate so the executor stays gated by construction.

Shadow Mode is deliberately distinct from ``dry_run``:

- ``dry_run`` is the fixture-replay path used for CI smoke tests and
  unit tests; the pipeline reads CSV bars and the risk gate is forced
  to a record-only HOLD when account / market snapshots are absent.
- ``shadow`` runs the SAME pipeline as live but replaces ``order_send``
  with an audit record. Account / market snapshots come from the
  bridge so the risk gate's decision is fully exercised.

### ``signal_direction`` in ``tick.success``

The shadow report joins ``tick.start`` (mode + symbol-timeframe) with
``tick.success`` (decision_time + signal_direction) by ``trace_id``,
then computes the realised direction over ``horizon_bars`` Closed Bars
after the decision. HOLD decisions are excluded from the accuracy
denominator: a HOLD that "happened to be right" tells us nothing about
the model.

### Promotion checklist

``run_promotion_checks`` exercises eight gates:

1. ``config_valid`` — re-validation via Pydantic ``model_dump`` round-trip.
2. ``mode_allowed`` — config mode matches the requested target.
3. ``small_live_constraints`` — exactly one enabled symbol, base risk
   ≤ 0.5%, daily loss cap ≤ 2%, drawdown cap ≤ 5%, ≤ 5 trades / day.
4. ``secrets_present`` — required env vars are set (default list
   covers the MT5 bridge).
5. ``kill_switch_path`` — parent dir of ``kill_switch_file`` exists
   and is writable so ``touch /path/STOP`` works without ``sudo``.
6. ``audit_path_writable`` — ``storage.audit_path`` exists and is
   writable; we never want a live tick to fail because of an audit
   open error.
7. ``backtest_report_recent`` — there is a backtest manifest no older
   than ``backtest_max_age_days`` (default 7).
8. ``commit_known`` — ``runtime_snapshot`` resolved a real commit SHA.

Every gate emits a structured ``PromotionCheckOutcome``
(``name``, ``passed``, ``detail``). The aggregate ``PromotionReport``
is JSON-serialisable for CI; the CLI exits 1 when any gate fails.

### Rollback

``runtime_snapshot(config, repo_root)`` returns ``(commit, config_hash)``
from the live process. The hash is a deterministic SHA-256 of the
config's JSON-serialisable dump, so two runs with the same config
produce the same fingerprint regardless of dict ordering. Operators
embed the snapshot in audit records (``tick.start``, soon) and in
promotion reports; the [rollback runbook](../runbooks/rollback.md)
shows the exact restore procedure.

## Alternatives considered

- **Reuse ``dry_run`` for live data**: would conflate two very
  different code paths and risk the executor being enabled by mistake.
  Rejected.
- **Embed the promotion checklist in the systemd unit**: would couple
  the operational gate to a specific deployment system. Keeping it in
  the CLI makes it portable and unit-testable.
- **Real-time promotion gating**: enforce gates on every tick rather
  than only at promotion time. Out of scope for this slice; the
  observability alerts already cover the runtime invariants
  (``data_expired``, ``kill_switch_engaged``, ``adapter_failure_rate_high``,
  ``drawdown_breach``).

## Consequences

- Adding a new mode is a one-line change in ``modes.py``, but the
  author must update ``allows_order_send`` and either
  ``small_live_constraints`` or document why no constraint applies.
- The shadow report is intentionally a sanity check, not a backtest
  replacement. Promotion still requires ``backtest_report_recent``.
- ``signal_direction`` becomes a stable audit field; consumers can
  rely on it, and any future change must be additive.
