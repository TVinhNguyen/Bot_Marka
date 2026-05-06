"""Issue #11 — runtime modes and the order_send gate.

The system supports six modes on a strict promotion ladder:

* ``dev`` — local development, no live data, no live execution.
* ``dry_run`` — fixture-replay path used by ``ai-mt5 dry-run-tick``;
  pipeline runs end-to-end but ``RiskManager`` is forced to a
  record-only HOLD when the account / market snapshot are absent.
* ``shadow`` — live data, no execution. Risk decisions are computed
  and audited so they can be compared with subsequent realised
  market direction. ``order_send`` MUST NOT fire.
* ``demo`` — broker demo account, execution allowed.
* ``staging`` — pre-prod broker (e.g. a second demo account or a
  sandbox), execution allowed, full monitoring required.
* ``small_live`` — production with reduced risk caps and a single
  symbol-timeframe.

The ``allows_order_send`` predicate is the single point that decides
whether the executor may fire. Any new mode added in future MUST be
added here so the executor stays gated.
"""

from __future__ import annotations

from enum import StrEnum


class RuntimeMode(StrEnum):
    """Canonical runtime mode. ``StrEnum`` keeps YAML / JSON friendly."""

    DEV = "dev"
    DRY_RUN = "dry_run"
    SHADOW = "shadow"
    DEMO = "demo"
    STAGING = "staging"
    SMALL_LIVE = "small_live"

    def __str__(self) -> str:
        return self.value


_LIVE_DATA_MODES: frozenset[RuntimeMode] = frozenset(
    {RuntimeMode.SHADOW, RuntimeMode.DEMO, RuntimeMode.STAGING, RuntimeMode.SMALL_LIVE}
)
_ORDER_SEND_MODES: frozenset[RuntimeMode] = frozenset(
    {RuntimeMode.DEMO, RuntimeMode.STAGING, RuntimeMode.SMALL_LIVE}
)


def parse_mode(value: str | RuntimeMode) -> RuntimeMode:
    """Coerce a config / CLI string into :class:`RuntimeMode`."""
    if isinstance(value, RuntimeMode):
        return value
    try:
        return RuntimeMode(value)
    except ValueError as exc:
        allowed = ", ".join(m.value for m in RuntimeMode)
        raise ValueError(f"unknown runtime mode {value!r}; expected one of: {allowed}") from exc


def is_live_capable(mode: RuntimeMode | str) -> bool:
    """True when the mode runs against live broker data.

    Note: shadow mode is live-data but NOT order-sending. Use
    :func:`allows_order_send` for the executor gate.
    """
    return parse_mode(mode) in _LIVE_DATA_MODES


def allows_order_send(mode: RuntimeMode | str) -> bool:
    """True when the executor is allowed to call ``order_send``.

    Single source of truth for the execution gate. Shadow / dry_run /
    dev all return ``False``.
    """
    return parse_mode(mode) in _ORDER_SEND_MODES


__all__ = ["RuntimeMode", "allows_order_send", "is_live_capable", "parse_mode"]
