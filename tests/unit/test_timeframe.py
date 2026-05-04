"""Issue #6: timeframe helpers."""

from __future__ import annotations

from datetime import timedelta

import pytest

from ai_mt5.data.timeframe import (
    TIMEFRAME_MINUTES,
    UnknownTimeframeError,
    timeframe_delta,
    timeframe_minutes,
)


@pytest.mark.parametrize(
    "timeframe,minutes",
    [
        ("M1", 1),
        ("M5", 5),
        ("M15", 15),
        ("M30", 30),
        ("H1", 60),
        ("H4", 240),
        ("D1", 1440),
    ],
)
def test_timeframe_minutes_and_delta(timeframe: str, minutes: int) -> None:
    assert timeframe_minutes(timeframe) == minutes
    assert timeframe_delta(timeframe) == timedelta(minutes=minutes)


def test_unknown_timeframe_raises() -> None:
    with pytest.raises(UnknownTimeframeError):
        timeframe_minutes("W1")


def test_registry_is_complete() -> None:
    assert TIMEFRAME_MINUTES["M15"] == 15
