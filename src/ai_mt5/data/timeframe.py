"""Helpers for broker Timeframe strings (``M1``, ``M15``, ``H1``, ``D1`` ...)."""

from __future__ import annotations

from datetime import timedelta

TIMEFRAME_MINUTES: dict[str, int] = {
    "M1": 1,
    "M5": 5,
    "M15": 15,
    "M30": 30,
    "H1": 60,
    "H4": 240,
    "D1": 60 * 24,
}


class UnknownTimeframeError(ValueError):
    """Raised when a timeframe string is not in :data:`TIMEFRAME_MINUTES`."""


def timeframe_minutes(timeframe: str) -> int:
    """Return the number of minutes in one bar of ``timeframe``."""
    try:
        return TIMEFRAME_MINUTES[timeframe]
    except KeyError as exc:
        raise UnknownTimeframeError(
            f"unknown timeframe {timeframe!r}; supported: {sorted(TIMEFRAME_MINUTES)}"
        ) from exc


def timeframe_delta(timeframe: str) -> timedelta:
    """Return the ``timedelta`` of one bar of ``timeframe``."""
    return timedelta(minutes=timeframe_minutes(timeframe))
