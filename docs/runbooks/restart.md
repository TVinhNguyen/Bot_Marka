# Restart

**Goal:** bring the system back up after a clean stop, demo to demo or
demo to staging only — never restart directly into Small Live without a
fresh promotion check.

## Commands

1. Confirm the kill switch is disengaged and the audit path is
   writable:

   ```bash
   ai-mt5 promotion-check --config /path/to/config.yaml --target demo
   ```

   Every gate must pass before you proceed. If any gate fails, fix the
   underlying issue (e.g. missing secret, stale backtest) — do not
   override.

2. Restart the supervisor:

   ```bash
   systemctl restart ai-mt5
   ```

3. Tail the structured log and confirm the first ``tick.start`` event:

   ```bash
   ai-mt5 health --config /path/to/config.yaml
   journalctl -u ai-mt5 -n 50 -f
   ```

## Rollback

If the first tick after restart fails, immediately apply the
[stop](./stop.md) runbook and then the [rollback](./rollback.md)
runbook to revert to the previous good commit + config.
