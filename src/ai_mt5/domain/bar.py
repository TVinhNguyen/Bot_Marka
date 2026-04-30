"""The Closed Bar: a completed OHLCV candle safe to use for features and forecasts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Bar:
    """A completed OHLCV candle.

    Attributes:
        symbol: Instrument name, e.g. ``"EURUSD"``.
        timeframe: Bar interval (``"M15"``, ``"H1"``, ...).
        open_time: UTC timestamp of the bar open.
        open, high, low, close: Standard OHLC.
        volume: Tick or contract volume (broker-defined).
        spread_points: Snapshot of spread at bar close, in broker points.
        is_closed: Always ``True`` for a Closed Bar; constructors enforce this.
    """

    symbol: str
    timeframe: str
    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    spread_points: int = 0
    is_closed: bool = True

    def __post_init__(self) -> None:
        if not self.is_closed:
            raise ValueError(
                f"Bar({self.symbol} {self.timeframe} @ {self.open_time}) is not "
                f"closed; only Closed Bars may be used for features and forecasts"
            )
        if self.open_time.tzinfo is None:
            raise ValueError("Bar.open_time must be timezone-aware (UTC)")
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("Bar high must be >= open/close/low")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("Bar low must be <= open/close/high")
        if self.volume < 0:
            raise ValueError("Bar volume must be non-negative")
