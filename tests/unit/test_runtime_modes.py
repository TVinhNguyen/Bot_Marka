"""Issue #11 — RuntimeMode and the order_send gate."""

from __future__ import annotations

import pytest

from ai_mt5.runtime.modes import (
    RuntimeMode,
    allows_order_send,
    is_live_capable,
    parse_mode,
)


@pytest.mark.parametrize(
    "value, expected",
    [
        ("dev", RuntimeMode.DEV),
        ("dry_run", RuntimeMode.DRY_RUN),
        ("shadow", RuntimeMode.SHADOW),
        ("demo", RuntimeMode.DEMO),
        ("staging", RuntimeMode.STAGING),
        ("small_live", RuntimeMode.SMALL_LIVE),
    ],
)
def test_parse_mode_round_trips(value: str, expected: RuntimeMode) -> None:
    assert parse_mode(value) is expected
    assert str(parse_mode(value)) == value


def test_parse_mode_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="unknown runtime mode"):
        parse_mode("production")


def test_shadow_mode_is_live_capable_but_not_order_send() -> None:
    """The whole point of Shadow Mode: live data, NO order_send."""
    assert is_live_capable(RuntimeMode.SHADOW) is True
    assert allows_order_send(RuntimeMode.SHADOW) is False


@pytest.mark.parametrize("mode", [RuntimeMode.DEV, RuntimeMode.DRY_RUN])
def test_offline_modes_neither_live_nor_order_send(mode: RuntimeMode) -> None:
    assert is_live_capable(mode) is False
    assert allows_order_send(mode) is False


@pytest.mark.parametrize("mode", [RuntimeMode.DEMO, RuntimeMode.STAGING, RuntimeMode.SMALL_LIVE])
def test_executing_modes_allow_order_send(mode: RuntimeMode) -> None:
    assert is_live_capable(mode) is True
    assert allows_order_send(mode) is True
