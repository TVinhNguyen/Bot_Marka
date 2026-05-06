# Rollback

**Goal:** revert to a previous commit + config snapshot referenced in
the audit trail.

Every ``tick.start`` audit record carries the runtime snapshot
(``commit`` + ``config_hash``). The promotion-check JSON also embeds
the snapshot so the operator can pin the exact state they want to
restore.

## Commands

1. Identify the target commit from the audit JSONL or a saved
   promotion report:

   ```bash
   jq -r 'select(.kind == "tick.start") | .payload.snapshot.commit' \
       /var/lib/ai-mt5/audit/audit.jsonl | sort -u | head
   ```

2. Engage the kill switch (see [stop.md](./stop.md)).

3. Check out the target commit and the config snapshot from version
   control:

   ```bash
   git fetch --all
   git checkout <commit-sha>
   cp config/snapshots/<commit-sha>.yaml config/config.yaml
   ```

4. Re-run the promotion check for the current target mode:

   ```bash
   ai-mt5 promotion-check --config config/config.yaml --target demo
   ```

5. Disengage the kill switch (see [restart.md](./restart.md)).

## Notes

- Never roll back directly to ``small_live`` — go via ``demo`` for at
  least one full session first.
- If ``commit`` is ``unknown`` in the audit trail, the system was
  running a non-git build; rollback requires deploying the previously
  released artefact and is out of scope for this runbook.
