"""Cost model for the walk-forward backtest.

The model converts broker frictions -- spread, commission, slippage buffer,
and overnight swap -- into deposit-currency cost amounts. It is pure: every
input is supplied by the caller, no I/O, no global state. The Risk Decision
gate already constrains volume; this module never re-validates it.

All point-denominated inputs are converted via ``point_size * contract_size``,
matching the same conversion used by :mod:`ai_mt5.risk.position_sizing`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CostModel:
    """Symbol-specific friction costs.

    Attributes:
        spread_points: Half-spread already implicitly included by
            entering at ``ask`` and exiting at ``bid``; this value covers
            *additional* spread beyond the snapshot used for entry, e.g.
            average widening at the close (in broker points).
        commission_per_lot: Round-trip commission (deposit currency per
            ``contract_size`` units), charged once at exit.
        slippage_buffer_points: Worst-case slippage at entry/exit, in
            broker points. Symmetric: applied once at entry, once at exit.
        swap_long_per_night: Overnight financing for a long position
            (deposit currency per ``contract_size`` per night). May be
            negative when the rollover is in the trader's favour.
        swap_short_per_night: Overnight financing for a short position.
        point_size: Broker point size (price units per point).
        contract_size: Broker contract size (e.g. ``100_000`` for FX).
    """

    spread_points: float = 0.0
    commission_per_lot: float = 0.0
    slippage_buffer_points: float = 0.0
    swap_long_per_night: float = 0.0
    swap_short_per_night: float = 0.0
    point_size: float = 0.0001
    contract_size: float = 100_000.0

    def __post_init__(self) -> None:
        if self.point_size <= 0:
            raise ValueError("point_size must be positive")
        if self.contract_size <= 0:
            raise ValueError("contract_size must be positive")
        if self.spread_points < 0:
            raise ValueError("spread_points must be >= 0")
        if self.commission_per_lot < 0:
            raise ValueError("commission_per_lot must be >= 0")
        if self.slippage_buffer_points < 0:
            raise ValueError("slippage_buffer_points must be >= 0")

    def entry_cost(self, volume: float) -> float:
        """Cost charged when the position opens, in deposit currency.

        Includes one slippage buffer at entry (the wider of bid/ask is the
        worst case the trader pays for an aggressive fill).
        """
        if volume <= 0:
            return 0.0
        return self.slippage_buffer_points * self.point_size * self.contract_size * volume

    def exit_cost(self, volume: float) -> float:
        """Cost charged when the position closes.

        Includes the residual ``spread_points`` (e.g. wider close-of-day
        spreads), one slippage buffer at exit, and round-trip commission.
        """
        if volume <= 0:
            return 0.0
        spread_cost = self.spread_points * self.point_size * self.contract_size * volume
        slip_cost = self.slippage_buffer_points * self.point_size * self.contract_size * volume
        commission = self.commission_per_lot * volume
        return spread_cost + slip_cost + commission

    def holding_cost(self, side: str, volume: float, n_nights: int) -> float:
        """Total swap charged for ``n_nights`` overnight rollovers.

        ``n_nights`` should be 0 for an intraday close. Negative swap
        (favourable rollover) is preserved verbatim and may reduce the
        round-trip cost.
        """
        if side not in ("BUY", "SELL"):
            raise ValueError(f"invalid side {side!r}")
        if volume <= 0 or n_nights <= 0:
            return 0.0
        per_night = self.swap_long_per_night if side == "BUY" else self.swap_short_per_night
        return per_night * volume * n_nights

    def total_cost(self, *, side: str, volume: float, n_nights: int) -> float:
        """Convenience: full round-trip cost for the trade."""
        return (
            self.entry_cost(volume)
            + self.exit_cost(volume)
            + self.holding_cost(side=side, volume=volume, n_nights=n_nights)
        )
