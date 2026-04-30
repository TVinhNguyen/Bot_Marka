# JSONL Audit Trail and Per-Tick Trace IDs

The Audit Trail is the source of truth for every Forecast, Meta-Signal, Risk Decision, and tick lifecycle event. The first implementation persists records as one JSON object per line under the `audit/` directory, fsync-flushed on every append, and never overwritten. A 32-character hex trace ID is generated at the start of each tick and propagated through `contextvars` so that structured logs and audit records can be correlated without explicit plumbing.

JSONL is chosen over a database for now because it gives us a portable, diffable, easily inspectable record while the contracts are still being shaped. Every record exposes `kind`, `trace_id`, `timestamp`, and `payload`, so a database-backed `AuditTrail` can be added later without touching call sites. Future slices may add hash chaining for governance; the dataclass intentionally reserves a `schema_version` field for that purpose.
