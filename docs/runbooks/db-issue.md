# DB / storage issue

**Goal:** recover from a JSONL audit / store path that has become
unwritable (disk full, permissions changed, mount lost).

## Symptoms

- TickRunner audit raises ``OSError`` writing to
  ``storage.audit_path``.
- ``ai-mt5 health`` exits non-zero with ``audit_path_writable=false``.
- Bar / forecast appends fail with ``ENOSPC`` or ``EACCES``.

## Commands

1. Engage the kill switch (see [stop.md](./stop.md)).

2. Diagnose:

   ```bash
   df -h /var/lib/ai-mt5
   ls -la /var/lib/ai-mt5/audit/
   stat -f /var/lib/ai-mt5
   ```

3. Free up space or fix permissions:

   ```bash
   # disk full -- archive old audit shards
   tar -czf /backup/audit-$(date +%F).tgz /var/lib/ai-mt5/audit/audit.jsonl
   : > /var/lib/ai-mt5/audit/audit.jsonl

   # permissions
   chown -R ai-mt5:ai-mt5 /var/lib/ai-mt5
   chmod 750 /var/lib/ai-mt5
   ```

4. Verify writability:

   ```bash
   ai-mt5 promotion-check --config /path/to/config.yaml --target demo
   ```

   ``audit_path_writable`` must pass.

5. Run reconciliation before resuming, since the audit gap may have
   hidden state changes:

   ```bash
   ai-mt5 reconcile --config /path/to/config.yaml --intent-log /var/lib/ai-mt5/intents.jsonl
   ```

6. Disengage the kill switch (see [restart.md](./restart.md)).

## Notes

- Truncating ``audit.jsonl`` breaks the hash chain (per ADR 0009). The
  archive copy is the source of truth for forensics; the live file
  starts a new chain after truncation. Document the rotation in your
  ops journal.
