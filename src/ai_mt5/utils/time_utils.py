"""UTC-only time helpers."""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    """Return the current time as a timezone-aware UTC ``datetime``."""
    return datetime.now(tz=UTC)


def to_iso(ts: datetime) -> str:
    """Format ``ts`` as an ISO-8601 UTC string (``...Z``)."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC).isoformat().replace("+00:00", "Z")
