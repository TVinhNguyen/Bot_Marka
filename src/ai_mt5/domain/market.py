"""Account, market, and news snapshots consumed by the Risk Decision gate."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

NewsImpact = Literal["high", "medium", "low"]


@dataclass(frozen=True)
class AccountSnapshot:
    """A point-in-time view of the broker account state.

    All values are expressed in the deposit currency of the account.
    """

    balance: float
    equity: float
    free_margin: float
    margin_used: float
    open_positions: int
    open_positions_for_symbol: int
    consecutive_losses: int
    trades_today: int
    daily_pnl_pct: float
    drawdown_pct: float
    timestamp: datetime

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None:
            raise ValueError("AccountSnapshot.timestamp must be timezone-aware (UTC)")


@dataclass(frozen=True)
class MarketSnapshot:
    """A point-in-time view of broker market state for a symbol."""

    symbol: str
    bid: float
    ask: float
    spread_points: int
    point_size: float
    contract_size: float
    volume_min: float
    volume_max: float
    volume_step: float
    stop_level_points: int
    atr: float
    margin_per_lot: float
    timestamp: datetime

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None:
            raise ValueError("MarketSnapshot.timestamp must be timezone-aware (UTC)")
        if self.ask < self.bid:
            raise ValueError("MarketSnapshot.ask must be >= bid")
        if self.point_size <= 0:
            raise ValueError("MarketSnapshot.point_size must be positive")


@dataclass(frozen=True)
class NewsEvent:
    """A scheduled news event used by the Risk gate's news-window check."""

    symbol: str
    impact: NewsImpact
    scheduled_at: datetime
    title: str = ""
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.scheduled_at.tzinfo is None:
            raise ValueError("NewsEvent.scheduled_at must be timezone-aware (UTC)")
