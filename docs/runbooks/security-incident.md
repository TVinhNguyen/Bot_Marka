# Security incident

**Goal:** contain a suspected secret leak or unauthorised access to the
trading host or its credentials.

## Triggers

- A trading credential (MT5 login / password / server, bridge host /
  port) appeared in chat, logs, screenshots, or a public commit.
- Unrecognised broker positions appear in reconcile output with a
  matching ``magic`` (someone else used our key).
- ``ai-mt5 health`` reports an unexpected open position count.
- An operator account was compromised (SSH key, password, 2FA).

## Commands

1. **Stop trading immediately** — see [stop.md](./stop.md).

2. **Rotate the affected credential** before any other action:

   - MT5 password: log into MetaQuotes Web / terminal and reset.
   - Operator SSH keys: rotate `~/.ssh/authorized_keys` on the host
     and revoke the compromised key in the source-of-truth secret
     store (org password manager).
   - Devin / CI tokens: revoke and reissue via the org admin console.

3. Update the secrets in the secret manager (org-level), NOT inline in
   any config file:

   ```bash
   # Re-run the secret request flow from the operator UI.
   # Never paste secrets into chat or commit them.
   ```

4. Reconcile to surface any unexpected positions:

   ```bash
   ai-mt5 reconcile --config /path/to/config.yaml --intent-log /var/lib/ai-mt5/intents.jsonl
   ```

   Manually close any ``broker_only`` position you cannot account for.

5. Re-run promotion-check before resuming:

   ```bash
   ai-mt5 promotion-check --config /path/to/config.yaml --target demo
   ```

6. Audit the log files for the period of compromise:

   ```bash
   journalctl -u ai-mt5 --since "<incident-start>" --until "<now>"
   jq 'select(.kind | startswith("risk_decision"))' /var/lib/ai-mt5/audit/audit.jsonl
   ```

7. File a post-incident note in the ops journal documenting:
   - timeline,
   - which credential leaked and how,
   - rotation timestamps,
   - any positions that had to be force-closed,
   - follow-up controls.

## Forbidden

- Do NOT continue trading on the original credentials hoping nothing
  was abused. The cost of a false negative is unbounded.
- Do NOT commit a "fixed" secret back into the repo — secrets live in
  the secret manager, never in version control.
