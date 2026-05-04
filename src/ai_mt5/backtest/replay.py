"""No-lookahead bar-by-bar replay primitives.

The replay engine never lets adapters or the ensemble see bars at or after
the decision time. It is the backtester's analogue of the dry_run tick:
features are built strictly from past bars, the entry decision is recorded
*before* the next bar's high/low touches a stop, and the realized PnL is
computed from the bar series alone -- no broker, no MT5.

Trade simulation is intentionally simple:

* A position opens at the close of bar ``t`` (the decision bar) at price
  ``entry_price`` (close + slippage already priced into the cost model).
* On each subsequent bar ``t+k``, we check stop-loss / take-profit hits
  using the bar's ``high`` / ``low``. SL is checked *first* (conservative
  worst-case ordering when a single bar straddles both levels).
* Exit price is the SL/TP level (gap-conservative); if neither triggers
  before the OOS range ends, the trade closes at the final close.

This is deterministic by construction: with the same bars and the same
adapter outputs, every replay yields the same trade ledger.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import pairwise
from typing import Literal

from ..domain.bar import Bar

Side = Literal["BUY", "SELL"]


@dataclass(frozen=True)
class SimulatedFill:
    """Outcome of opening and closing a single position."""

    side: Side
    volume: float
    entry_price: float
    exit_price: float
    sl: float
    tp: float
    open_idx: int
    close_idx: int
    open_time: str  # ISO-8601 (frozen for audit-friendly serialization)
    close_time: str
    bars_held: int
    nights_held: int
    exit_reason: Literal["stop_loss", "take_profit", "end_of_window"]

    @property
    def gross_pnl_price(self) -> float:
        """Per-unit price PnL, *before* contract size and cost."""
        if self.side == "BUY":
            return self.exit_price - self.entry_price
        return self.entry_price - self.exit_price


def _count_nights(open_time_iso: str, close_time_iso: str) -> int:
    """Conservative estimate of overnight rollovers between two ISO times.

    Counts UTC date boundaries crossed; if the trade spans 0 days the count
    is 0. Avoids reading the broker's actual rollover schedule -- close
    enough for an offline backtest.
    """
    open_dt = datetime.fromisoformat(open_time_iso)
    close_dt = datetime.fromisoformat(close_time_iso)
    if close_dt <= open_dt:
        return 0
    nights = (close_dt.date() - open_dt.date()).days
    return max(0, nights)


def simulate_trade(
    bars: list[Bar],
    *,
    side: Side,
    volume: float,
    entry_idx: int,
    entry_price: float,
    sl: float,
    tp: float,
    oos_end_idx: int,
) -> SimulatedFill:
    """Walk forward from ``entry_idx`` until SL/TP hits or OOS ends.

    The position is assumed to open at the close of ``bars[entry_idx]``.
    Stops are checked from ``entry_idx + 1`` onward so the same bar that
    triggered the entry decision can never also exit the trade. ``oos_end_idx``
    is exclusive (matching :class:`IndexRange`).
    """
    if entry_idx < 0 or entry_idx >= len(bars):
        raise ValueError("entry_idx out of range")
    if oos_end_idx <= entry_idx:
        raise ValueError("oos_end_idx must be after entry_idx")
    if volume <= 0:
        raise ValueError("volume must be positive")

    open_bar = bars[entry_idx]
    last_idx = min(oos_end_idx, len(bars)) - 1

    for k in range(entry_idx + 1, last_idx + 1):
        bar = bars[k]
        # SL first: worst-case assumption when a single bar covers both levels.
        if side == "BUY":
            if bar.low <= sl:
                return _fill(
                    side,
                    volume,
                    entry_price,
                    sl,
                    sl,
                    tp,
                    open_bar,
                    bar,
                    entry_idx,
                    k,
                    "stop_loss",
                )
            if bar.high >= tp:
                return _fill(
                    side,
                    volume,
                    entry_price,
                    tp,
                    sl,
                    tp,
                    open_bar,
                    bar,
                    entry_idx,
                    k,
                    "take_profit",
                )
        else:
            if bar.high >= sl:
                return _fill(
                    side,
                    volume,
                    entry_price,
                    sl,
                    sl,
                    tp,
                    open_bar,
                    bar,
                    entry_idx,
                    k,
                    "stop_loss",
                )
            if bar.low <= tp:
                return _fill(
                    side,
                    volume,
                    entry_price,
                    tp,
                    sl,
                    tp,
                    open_bar,
                    bar,
                    entry_idx,
                    k,
                    "take_profit",
                )

    # Neither SL nor TP fired -> close at the final available bar's close.
    final_bar = bars[last_idx]
    return _fill(
        side,
        volume,
        entry_price,
        final_bar.close,
        sl,
        tp,
        open_bar,
        final_bar,
        entry_idx,
        last_idx,
        "end_of_window",
    )


def _fill(
    side: Side,
    volume: float,
    entry_price: float,
    exit_price: float,
    sl: float,
    tp: float,
    open_bar: Bar,
    close_bar: Bar,
    open_idx: int,
    close_idx: int,
    reason: Literal["stop_loss", "take_profit", "end_of_window"],
) -> SimulatedFill:
    open_iso = open_bar.open_time.isoformat()
    close_iso = close_bar.open_time.isoformat()
    return SimulatedFill(
        side=side,
        volume=volume,
        entry_price=entry_price,
        exit_price=exit_price,
        sl=sl,
        tp=tp,
        open_idx=open_idx,
        close_idx=close_idx,
        open_time=open_iso,
        close_time=close_iso,
        bars_held=close_idx - open_idx,
        nights_held=_count_nights(open_iso, close_iso),
        exit_reason=reason,
    )


def estimate_atr(bars: list[Bar], end_idx: int, window: int = 14) -> float:
    """True-range ATR using bars strictly before ``end_idx``.

    The replay calls this to feed :func:`compute_sl_tp` without leaking the
    decision bar. Returns ``0.0`` for windows shorter than ``window + 1``;
    the Risk gate then rejects the trade with ``invalid_atr``.
    """
    lo = max(0, end_idx - window - 1)
    hi = end_idx  # exclusive: bars[lo:hi] is strictly past
    slice_ = bars[lo:hi]
    if len(slice_) < 2:
        return 0.0
    trs: list[float] = []
    for prev, cur in pairwise(slice_):
        tr = max(
            cur.high - cur.low,
            abs(cur.high - prev.close),
            abs(cur.low - prev.close),
        )
        trs.append(tr)
    if not trs:
        return 0.0
    return sum(trs) / len(trs)


def bar_duration(bars: list[Bar]) -> timedelta:
    """Median bar duration; falls back to 15 minutes when ambiguous."""
    if len(bars) < 2:
        return timedelta(minutes=15)
    deltas: list[timedelta] = []
    for prev, cur in pairwise(bars):
        d = cur.open_time - prev.open_time
        if d.total_seconds() > 0:
            deltas.append(d)
    if not deltas:
        return timedelta(minutes=15)
    deltas.sort()
    return deltas[len(deltas) // 2]
