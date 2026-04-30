"""SL/TP computation.

Stop-loss distance is anchored to ATR and clamped to:

* ``[sl_atr_min * ATR, sl_atr_max * ATR]``
* a broker-side floor expressed in points (``stop_level_points * point_size``).

Take-profit is set so the realized risk-reward ratio is at least ``rr_min``
and at least ``tp_atr * ATR``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StopsResult:
    sl: float
    tp: float
    sl_distance_price: float
    rejected_by: list[str]

    @property
    def approved(self) -> bool:
        return not self.rejected_by


def compute_sl_tp(
    *,
    side: str,
    entry_price: float,
    atr: float,
    sl_atr_min: float,
    sl_atr_max: float,
    tp_atr: float,
    rr_min: float,
    stop_level_points: int,
    point_size: float,
) -> StopsResult:
    """Return SL/TP for ``side`` at ``entry_price``.

    Inputs are expressed in price units (not pips/points) so the function is
    independent of broker conventions.
    """
    rejected: list[str] = []
    if atr <= 0:
        return StopsResult(sl=0.0, tp=0.0, sl_distance_price=0.0, rejected_by=["invalid_atr"])
    if entry_price <= 0:
        return StopsResult(
            sl=0.0, tp=0.0, sl_distance_price=0.0, rejected_by=["invalid_entry_price"]
        )
    if side not in ("BUY", "SELL"):
        return StopsResult(sl=0.0, tp=0.0, sl_distance_price=0.0, rejected_by=["invalid_side"])
    if sl_atr_min > sl_atr_max:
        return StopsResult(sl=0.0, tp=0.0, sl_distance_price=0.0, rejected_by=["invalid_atr_band"])

    target_sl_distance = sl_atr_min * atr
    broker_floor = stop_level_points * point_size
    sl_distance = max(target_sl_distance, broker_floor)
    sl_distance = min(sl_distance, sl_atr_max * atr)
    if sl_distance < broker_floor:
        rejected.append("sl_below_broker_stop_level")

    tp_distance = max(tp_atr * atr, rr_min * sl_distance)

    if side == "BUY":
        sl = entry_price - sl_distance
        tp = entry_price + tp_distance
    else:
        sl = entry_price + sl_distance
        tp = entry_price - tp_distance

    if sl <= 0 or tp <= 0:
        rejected.append("non_positive_sl_or_tp")

    if rejected:
        return StopsResult(sl=0.0, tp=0.0, sl_distance_price=0.0, rejected_by=rejected)

    return StopsResult(sl=sl, tp=tp, sl_distance_price=sl_distance, rejected_by=[])
