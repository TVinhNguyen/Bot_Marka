# MT5 disconnect

**Goal:** detect and recover from a lost MT5 RPyC bridge connection
without leaving stale local intents.

## Symptoms

- ``ai-mt5 health`` shows ``mt5.connected=false``.
- ``ai-mt5 mt5-preflight`` emits a structured failure with
  ``bridge_error:`` or ``bridge_transport_error:`` prefix.
- TickRunner audit records the failure as
  ``kind="tick.failure"`` with an ``EOFError`` /
  ``ConnectionResetError`` / ``OSError`` / ``TimeoutError``.

## Commands

1. Engage the kill switch — no new orders should be attempted while the
   bridge is down (see [stop.md](./stop.md)).

2. Verify the Windows bridge is up. On the bridge host:

   ```powershell
   Get-Process | Where-Object { $_.ProcessName -like "*mt5linux*" }
   netstat -ano | findstr :18812
   ```

3. Restart the bridge:

   ```powershell
   python -m mt5linux <path-to-python.exe>
   ```

4. From the operator host, confirm preflight:

   ```bash
   ai-mt5 mt5-preflight --config /path/to/config.yaml
   ```

5. Run reconciliation BEFORE disengaging the kill switch:

   ```bash
   ai-mt5 reconcile --config /path/to/config.yaml --intent-log /var/lib/ai-mt5/intents.jsonl
   ```

   - ``broker_only`` positions: investigate; do not auto-attach.
   - ``timeout_pending`` intents: operator decides per ADR 0011.
   - ``local_only`` intents: trade was likely closed at the broker
     while the bridge was down; mark the intent ``closed`` from
     history.

6. Disengage the kill switch (see [restart.md](./restart.md)).
