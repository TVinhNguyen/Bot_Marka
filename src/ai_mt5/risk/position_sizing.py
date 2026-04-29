"""Position sizing math.

Sizing turns a target *risk amount* (in deposit currency) into a broker-valid
volume that:

* respects the broker's volume_min / volume_max / volume_step,
* never exceeds ``max_risk_per_trade`` of equity, and
* never falls below ``min_risk_per_trade`` (rejected by caller if so).

The contract is intentionally pure: this function never reads config, account,
or market state directly; the :class:`RiskManager` composes those inputs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class SizingResult:
    """Outcome of sizing a position."""

    volume: float
    risk_amount: float
    rejected_by: list[str]

    @property
    def approved(self) -> bool:
        return not self.rejected_by and self.volume > 0


def _round_to_step(value: float, step: float) -> float:
    if step <= 0:
        raise ValueError("step must be positive")
    return math.floor(value / step) * step


def size_position(
    *,
    equity: float,
    base_risk_pct: float,
    min_risk_pct: float,
    max_risk_pct: float,
    sl_distance_price: float,
    contract_size: float,
    volume_min: float,
    volume_max: float,
    volume_step: float,
) -> SizingResult:
    """Compute a broker-valid trade volume.

    Args:
        equity: Account equity in deposit currency.
        base_risk_pct: Target risk per trade as a fraction of equity.
        min_risk_pct: Hard floor for risk per trade.
        max_risk_pct: Hard ceiling for risk per trade.
        sl_distance_price: Distance from entry to SL, in price units.
        contract_size: Broker contract size (e.g. 100_000 for FX majors).
        volume_min/max/step: Broker volume constraints.
    """
    rejected: list[str] = []
    if equity <= 0:
        return SizingResult(volume=0.0, risk_amount=0.0, rejected_by=["non_positive_equity"])
    if sl_distance_price <= 0:
        return SizingResult(volume=0.0, risk_amount=0.0, rejected_by=["invalid_sl_distance"])
    if not (0 < min_risk_pct <= base_risk_pct <= max_risk_pct):
        return SizingResult(
            volume=0.0,
            risk_amount=0.0,
            rejected_by=["invalid_risk_pct_band"],
        )

    target_risk = equity * base_risk_pct
    raw_volume = target_risk / (sl_distance_price * contract_size)
    stepped = _round_to_step(raw_volume, volume_step)

    if stepped < volume_min:
        rejected.append("volume_below_min")
        stepped = 0.0
    if stepped > volume_max:
        stepped = _round_to_step(volume_max, volume_step)

    actual_risk = stepped * sl_distance_price * contract_size
    if stepped > 0 and actual_risk > equity * max_risk_pct:
        rejected.append("risk_exceeds_max_cap")
        stepped = 0.0
        actual_risk = 0.0
    if stepped > 0 and actual_risk < equity * min_risk_pct:
        rejected.append("risk_below_min_cap")
        stepped = 0.0
        actual_risk = 0.0

    return SizingResult(volume=stepped, risk_amount=actual_risk, rejected_by=rejected)
