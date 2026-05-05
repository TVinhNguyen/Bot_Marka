# ADR 0010: MT5 RPyC bridge + Closed Bar preflight

## Status

Accepted — 2026-04-29

## Context

The bot orchestrator runs on Linux but the official `MetaTrader5` Python
package is **Windows-only**. ADR 0003 picked direct Python ↔ MT5
control as the MVP execution path; we still want that surface, just from
Linux. We also need to satisfy issue #3 (Closed Bar preflight + dry_run
`order_check`) before the live tick loop is allowed to send real orders.

## Decision

- **Bridge transport: `mt5linux` RPyC.** A Windows host runs
  `python -m mt5linux <python.exe>` which exposes the local
  `MetaTrader5` module over RPyC. The Linux orchestrator connects to
  that host and gets a remote handle to the module.
- **Linux-side dependency is `rpyc` only**, behind an optional
  `mt5` extra. The official `MetaTrader5` package is **never** imported
  on this side.
- **Narrow client surface.** `MT5Client` exposes only the methods we
  need: `terminal_info`, `account_info`, `symbol_info`,
  `symbol_info_tick`, `copy_rates_from_pos` (only positions ≥ 1 → no
  Running Bar), `positions`, `order_check`. **No `order_send`**;
  execution path will land in a separate ADR alongside issue #5.
- **Connection config** comes from environment variables
  (`MT5_BRIDGE_HOST`, `MT5_BRIDGE_PORT`, `MT5_DEMO_LOGIN`,
  `MT5_DEMO_PASSWORD`, `MT5_DEMO_SERVER`) so credentials never live in
  source. `MT5BridgeConfig.from_env()` is the only place these are
  read.
- **Closed Bar preflight.** `run_preflight(client, config, now)`:
  1. Verifies `terminal_info().connected` and `trade_allowed`.
  2. Verifies `account_info().trade_allowed`.
  3. Verifies the configured symbol is `visible` and `trade_mode != 0`.
  4. Pulls the latest `bar_count` bars with `start_pos=1` (skip Running
     Bar) and runs the same `run_quality_gates()` the live `TickRunner`
     uses.
  5. Calls `order_check` with a synthetic minimum-volume market order
     using the configured `magic` / `comment` / `deviation`. Accepted
     retcodes are `TRADE_RETCODE_DONE`, `_PLACED`, `_DONE_PARTIAL`.
  Returns a `PreflightReport` with `ok`, structured `failures`, and
  `to_dict()` for audit / CLI emission.
- **CLI surface.** `ai-mt5 mt5-preflight --config ... [--bar-count]
  [--volume]` runs the preflight and exits non-zero on failure so
  operators (and CI) can gate other commands on it.
- **Health integration.** `MT5BridgeStatus` is a
  `MT5StatusProvider` (ADR 0009) backed by `MT5Client`. The
  `ai-mt5 health` command can now report live MT5 state instead of the
  default `DisconnectedMT5Status` stub.

## Consequences

- The bot retains its deterministic Linux test environment; live MT5
  remains opt-in via the `mt5` extra and an explicit bridge address.
- Mocking is straightforward: any object with the same method
  signatures as the remote `MetaTrader5` module plugs into `MT5Client`,
  so unit tests for issue #3 cover the full surface without any RPyC
  hop.
- Issue #5 (broker reconciliation) and #11 (shadow mode + promotion
  gates) build on the same client without re-opening the transport
  question.

## Alternatives rejected

- **Wine on the orchestrator VM.** Setting up Wine + Windows Python +
  MetaTrader5 terminal on the bot VM is brittle, slow to boot, and
  couples the trading host to a desktop GUI. The bridge keeps each side
  doing what it is good at.
- **Custom socket protocol.** RPyC already gives us full module access
  with very little glue; rolling our own protocol would just re-derive
  RPyC features we depend on (timeouts, structured errors, netrefs).
- **Importing `MetaTrader5` directly on Linux via stub package.** No
  upstream-supported stub exists; vendoring one would mean shipping
  Windows-only types and pretending to talk to a broker we cannot
  actually reach.
