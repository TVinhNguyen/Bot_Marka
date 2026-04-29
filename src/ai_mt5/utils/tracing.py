"""Trace IDs for end-to-end correlation.

A trace ID is generated once per tick and propagated to every structured log
record and audit trail entry produced during that tick. Downstream slices
(MT5 preflight, executor, reconciliation) are expected to read the active
trace ID from :data:`trace_id_var` rather than passing it explicitly.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

trace_id_var: ContextVar[str | None] = ContextVar("ai_mt5_trace_id", default=None)


def new_trace_id() -> str:
    """Return a fresh, opaque trace ID."""
    return uuid.uuid4().hex


def current_trace_id() -> str | None:
    """Return the trace ID active in the current context, or ``None``."""
    return trace_id_var.get()


@contextmanager
def with_trace_id(trace_id: str | None = None) -> Iterator[str]:
    """Set ``trace_id`` (or a new one) for the duration of the ``with`` block."""
    tid = trace_id or new_trace_id()
    token = trace_id_var.set(tid)
    try:
        yield tid
    finally:
        trace_id_var.reset(token)
