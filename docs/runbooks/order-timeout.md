# Order timeout

**Goal:** safely handle a tick where ``order_send`` did not return in
time. Per issue #5, the bot MUST NOT auto-retry — only the operator
decides.

## Symptoms

- Audit JSONL contains a ``LocalIntent`` whose state is ``timeout``.
- ``ai-mt5 reconcile`` lists the intent under ``timeout_pending``.

## Commands

1. Engage the kill switch (see [stop.md](./stop.md)) so no further
   ticks fire while triage is in progress.

2. Run reconciliation to compare the local intent log with the broker:

   ```bash
   ai-mt5 reconcile --config /path/to/config.yaml --intent-log /var/lib/ai-mt5/intents.jsonl
   ```

3. Decide the outcome based on the JSON output:

   - **Timeout intent matches a broker position by `(magic, comment)`:**
     the order DID fill. Promote the intent manually to ``submitted``
     by appending a `LocalIntent` record with the new ``state`` and
     the broker ``ticket``. Do not call ``order_send`` again.

   - **Timeout intent has no matching broker position:** the order did
     not fill. Append a `LocalIntent` record marking the intent
     ``orphaned``. The next tick is free to re-evaluate the signal
     from scratch.

   - **Multiple broker positions match (duplicate fill):** one is
     attached to the intent (use the matching ``ticket`` if known);
     the rest appear as ``broker_only`` and must be manually closed
     by the operator on the broker terminal.

4. Re-run reconcile and confirm no entries remain in
   ``timeout_pending`` or ``broker_only``.

5. Disengage the kill switch (see [restart.md](./restart.md)).

## References

- ADR 0011 — Broker / local reconciliation
- Issue #5 — "Reconcile broker and local trade state after startup or timeout"
