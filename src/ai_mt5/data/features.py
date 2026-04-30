"""Anti-leak feature builder.

Features are computed using only Closed Bars whose ``open_time`` is strictly
earlier than the *decision bar's* ``open_time``. This guarantees that the
feature row used to make a forecast at decision time ``T`` has zero
information about the bar at time ``T``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import pairwise

from ..domain.bar import Bar


@dataclass(frozen=True)
class FeatureSet:
    """A small, deterministic set of features for the Baseline.

    The design here is intentionally minimal -- richer feature engineering
    belongs in the model adapter slices. What matters for issue #2 is that
    every value is derivable from data strictly before the decision bar.
    """

    decision_time: str  # ISO-8601 string for serialization
    last_close: float
    return_1: float
    return_5: float
    sma_5: float
    sma_20: float
    momentum_5: float
    realized_vol_20: float
    n_bars_used: int


def build_features(history: list[Bar], decision_bar: Bar) -> FeatureSet:
    """Build a :class:`FeatureSet` from ``history`` for ``decision_bar``.

    ``history`` must contain only bars whose ``open_time`` is strictly less
    than ``decision_bar.open_time``. The decision bar itself must NEVER be
    included; doing so is treated as look-ahead leakage and raises.
    """
    if not history:
        raise ValueError("build_features requires at least one historical bar")

    for bar in history:
        if bar.open_time >= decision_bar.open_time:
            raise ValueError(
                "look-ahead leakage detected: history contains a bar at or after "
                f"decision_time {decision_bar.open_time.isoformat()}"
            )

    closes = [b.close for b in history]
    n = len(closes)
    last_close = closes[-1]

    def ret(lookback: int) -> float:
        if n <= lookback:
            return 0.0
        prev = closes[-lookback - 1]
        if prev == 0:
            return 0.0
        return (last_close - prev) / prev

    def sma(window: int) -> float:
        slice_ = closes[-window:] if n >= window else closes
        return sum(slice_) / len(slice_)

    def realized_vol(window: int) -> float:
        slice_ = closes[-(window + 1) :] if n >= window + 1 else closes
        if len(slice_) < 2:
            return 0.0
        rets = []
        for prev, cur in pairwise(slice_):
            if prev == 0:
                continue
            rets.append((cur - prev) / prev)
        if len(rets) < 2:
            return 0.0
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
        return math.sqrt(var)

    return FeatureSet(
        decision_time=decision_bar.open_time.isoformat(),
        last_close=last_close,
        return_1=ret(1),
        return_5=ret(5),
        sma_5=sma(5),
        sma_20=sma(20),
        momentum_5=last_close - sma(5),
        realized_vol_20=realized_vol(20),
        n_bars_used=n,
    )
