# Stop

**Goal:** halt all trading immediately. No new orders are sent until the
operator explicitly restarts.

## Commands

1. Engage the kill switch (file-based, no service restart needed):

   ```bash
   touch /var/run/ai-mt5/STOP
   ```

   The exact path is `risk.kill_switch_file` in the active config.

2. Verify the next tick is rejected:

   ```bash
   ai-mt5 health --config /path/to/config.yaml
   ```

   Expect `kill_switch.engaged=true` in the JSON output and a non-zero
   exit code.

## Rollback

```bash
rm /var/run/ai-mt5/STOP
```

The next scheduled tick will resume normally. Audit JSONL records
``kill_switch_engaged=true`` until the file is removed, so the timeline
of the halt is preserved.
