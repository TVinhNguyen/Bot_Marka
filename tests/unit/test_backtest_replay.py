"""No-lookahead replay primitives: simulate_trade, estimate_atr."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ai_mt5.backtest import estimate_atr, simulate_trade
from ai_mt5.domain.bar import Bar


def _bar(
    minute: int,
    *,
    open_: float,
    high: float,
    low: float,
    close: float,
    spread: int = 10,
) -> Bar:
    return Bar(
        symbol="EURUSD",
        timeframe="M15",
        open_time=datetime(2026, 4, 29, 8, 0, tzinfo=UTC) + timedelta(minutes=minute),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=1_000.0,
        spread_points=spread,
    )


def _trending_bars(n: int, *, base: float = 1.0700, step: float = 0.0001) -> list[Bar]:
    bars: list[Bar] = []
    for i in range(n):
        close = base + step * i
        bars.append(
            _bar(
                15 * i,
                open_=close - 0.00005,
                high=close + 0.00010,
                low=close - 0.00010,
                close=close,
            )
        )
    return bars


def test_simulate_buy_take_profit() -> None:
    bars = _trending_bars(20)
    fill = simulate_trade(
        bars,
        side="BUY",
        volume=0.1,
        entry_idx=5,
        entry_price=bars[5].close,
        sl=bars[5].close - 0.0010,
        tp=bars[5].close + 0.00015,  # close + 1.5 pips
        oos_end_idx=20,
    )
    assert fill.exit_reason == "take_profit"
    assert fill.exit_price == pytest.approx(bars[5].close + 0.00015)
    assert fill.close_idx > fill.open_idx
    assert fill.bars_held == fill.close_idx - fill.open_idx


def test_simulate_buy_stop_loss() -> None:
    bars = _trending_bars(10, step=-0.0001)  # downtrend
    fill = simulate_trade(
        bars,
        side="BUY",
        volume=0.1,
        entry_idx=2,
        entry_price=bars[2].close,
        sl=bars[2].close - 0.00015,  # close enough to be hit
        tp=bars[2].close + 0.0050,
        oos_end_idx=10,
    )
    assert fill.exit_reason == "stop_loss"
    assert fill.exit_price == pytest.approx(bars[2].close - 0.00015)


def test_simulate_falls_through_to_end_of_window() -> None:
    bars = _trending_bars(10)
    # SL/TP both outside any reachable price -> end_of_window
    fill = simulate_trade(
        bars,
        side="BUY",
        volume=0.1,
        entry_idx=0,
        entry_price=bars[0].close,
        sl=bars[0].close - 1.0,
        tp=bars[0].close + 1.0,
        oos_end_idx=10,
    )
    assert fill.exit_reason == "end_of_window"
    assert fill.close_idx == 9  # last index before oos_end_idx


def test_simulate_rejects_oos_end_at_or_before_entry() -> None:
    bars = _trending_bars(5)
    with pytest.raises(ValueError):
        simulate_trade(
            bars,
            side="BUY",
            volume=0.1,
            entry_idx=3,
            entry_price=bars[3].close,
            sl=bars[3].close - 0.001,
            tp=bars[3].close + 0.001,
            oos_end_idx=3,
        )


def test_simulate_never_exits_on_entry_bar() -> None:
    """Same bar that triggers entry must not also exit the trade.

    We construct an entry bar whose own [low, high] already crosses both
    SL and TP. The replay must walk to the *next* bar before exiting.
    """
    bars = _trending_bars(5)
    # mutate entry bar so its high reaches TP and its low reaches SL
    entry = bars[2]
    target_close = entry.close
    bars[2] = Bar(
        symbol=entry.symbol,
        timeframe=entry.timeframe,
        open_time=entry.open_time,
        open=target_close,
        high=target_close + 0.005,
        low=target_close - 0.005,
        close=target_close,
        volume=entry.volume,
        spread_points=entry.spread_points,
    )
    fill = simulate_trade(
        bars,
        side="BUY",
        volume=0.1,
        entry_idx=2,
        entry_price=target_close,
        sl=target_close - 0.001,
        tp=target_close + 0.001,
        oos_end_idx=5,
    )
    assert fill.open_idx == 2
    assert fill.close_idx >= 3  # not 2; the entry bar can never exit


def test_estimate_atr_zero_for_short_history() -> None:
    bars = _trending_bars(3)
    assert estimate_atr(bars, end_idx=2, window=14) >= 0.0
    assert estimate_atr(bars, end_idx=1) == 0.0


def test_estimate_atr_uses_only_past_bars() -> None:
    """ATR computed at end_idx must not look at bars[end_idx] or later."""
    bars = _trending_bars(20)
    atr_clean = estimate_atr(bars, end_idx=10, window=5)
    # mutate bars at and after end_idx; ATR must be unchanged
    for i in range(10, 20):
        b = bars[i]
        bars[i] = Bar(
            symbol=b.symbol,
            timeframe=b.timeframe,
            open_time=b.open_time,
            open=b.open,
            high=b.high + 5.0,  # huge perturbation
            low=b.low - 5.0,
            close=b.close,
            volume=b.volume,
            spread_points=b.spread_points,
        )
    atr_after_future_perturb = estimate_atr(bars, end_idx=10, window=5)
    assert atr_clean == atr_after_future_perturb
