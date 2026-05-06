# Operator runbooks

Short operational procedures for the AI-MT5 system. Each runbook is
intentionally minimal: a one-line goal, the exact commands to run, the
expected output, and the rollback step. They are designed to be
executable from a phone terminal during an incident.

| Runbook | When to use |
| ------- | ----------- |
| [stop.md](./stop.md) | Halt all trading immediately. |
| [restart.md](./restart.md) | Bring the system back up after a clean stop. |
| [rollback.md](./rollback.md) | Revert to a previous commit + config snapshot. |
| [mt5-disconnect.md](./mt5-disconnect.md) | RPyC bridge drops or MT5 terminal logs out. |
| [order-timeout.md](./order-timeout.md) | `order_send` did not return in time. |
| [db-issue.md](./db-issue.md) | JSONL audit / store path becomes unwritable. |
| [security-incident.md](./security-incident.md) | Suspected secret leak or unauthorised access. |

All runbooks assume the `ai-mt5` CLI is on `PATH` and the operator has
write access to the configured `storage.audit_path` and the kill-switch
directory.
