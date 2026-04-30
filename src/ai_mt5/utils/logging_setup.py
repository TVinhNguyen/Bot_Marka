"""Structured JSON logging via structlog.

Every record automatically picks up the active trace ID (if any), the event
name, and an ISO-8601 UTC timestamp. The output is line-delimited JSON so it
can be ingested by any standard log shipper.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from typing import Any, TextIO

import structlog

from .tracing import current_trace_id


def _add_trace_id(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    tid = current_trace_id()
    if tid is not None and "trace_id" not in event_dict:
        event_dict["trace_id"] = tid
    return event_dict


def configure_logging(level: str = "INFO", *, stream: TextIO | None = None) -> None:
    """Configure structlog + stdlib logging to emit one JSON object per line.

    Safe to call multiple times; the last call wins.
    """
    out_stream = stream if stream is not None else sys.stdout

    logging.basicConfig(
        format="%(message)s",
        stream=out_stream,
        level=getattr(logging, level.upper(), logging.INFO),
        force=True,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _add_trace_id,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(sort_keys=True),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        context_class=dict,
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "ai_mt5") -> structlog.stdlib.BoundLogger:
    """Return a structlog logger bound to ``name``."""
    return structlog.get_logger(name)
