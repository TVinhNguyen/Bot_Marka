"""Metric arithmetic for the walk-forward backtest."""

from __future__ import annotations

import math

import pytest

from ai_mt5.backtest import compute_metrics, equity_curve, max_drawdown


def test_equity_curve_starts_at_initial_equity() -> None:
    curve = equity_curve(initial_equity=1_000.0, trade_pnls=[10.0, -5.0, 2.0])
    assert curve == [1_000.0, 1_010.0, 1_005.0, 1_007.0]


def test_max_drawdown_zero_when_monotone_up() -> None:
    abs_dd, frac_dd = max_drawdown([100.0, 110.0, 120.0])
    assert abs_dd == 0.0
    assert frac_dd == 0.0


def test_max_drawdown_picks_worst_peak_to_trough() -> None:
    abs_dd, frac_dd = max_drawdown([100.0, 120.0, 80.0, 140.0, 100.0])
    assert abs_dd == pytest.approx(40.0)  # 120 -> 80
    assert frac_dd == pytest.approx(40.0 / 120.0)


def test_compute_metrics_n_trades_and_win_rate() -> None:
    m = compute_metrics(
        [10.0, -5.0, 2.0, -1.0, 0.0],
        initial_equity=1_000.0,
        bars_per_year=24_000.0,
    )
    # break-even (0.0) is neither win nor loss
    assert m.n_trades == 5
    assert m.n_wins == 2
    assert m.n_losses == 2
    assert m.win_rate == pytest.approx(2 / 5)


def test_compute_metrics_profit_factor_no_losses_returns_inf() -> None:
    m = compute_metrics([5.0, 2.0, 1.0], initial_equity=1_000.0, bars_per_year=24_000.0)
    assert math.isinf(m.profit_factor) and m.profit_factor > 0


def test_compute_metrics_profit_factor_zero_when_no_trades() -> None:
    m = compute_metrics([], initial_equity=1_000.0, bars_per_year=24_000.0)
    assert m.profit_factor == 0.0
    assert m.n_trades == 0


def test_compute_metrics_sharpe_zero_when_zero_variance() -> None:
    m = compute_metrics([5.0, 5.0, 5.0], initial_equity=1_000.0, bars_per_year=24_000.0)
    assert m.sharpe == 0.0


def test_compute_metrics_sharpe_positive_for_winning_streak_with_variance() -> None:
    m = compute_metrics(
        [5.0, 1.0, 4.0, 3.0],
        initial_equity=1_000.0,
        bars_per_year=24_000.0,
        bars_per_trade=4.0,
    )
    assert m.sharpe > 0


def test_compute_metrics_calmar_zero_when_no_drawdown() -> None:
    m = compute_metrics([5.0, 5.0], initial_equity=1_000.0, bars_per_year=24_000.0)
    # peaks always rising -> dd_frac = 0 -> calmar = 0
    assert m.calmar == 0.0


def test_compute_metrics_calmar_uses_drawdown_fraction() -> None:
    m = compute_metrics(
        [50.0, -200.0, 100.0],
        initial_equity=1_000.0,
        bars_per_year=24_000.0,
    )
    # -200 after first trade: peak 1050 -> trough 850 -> dd_frac = 200/1050
    assert m.max_drawdown_pct == pytest.approx(200.0 / 1050.0)
    expected_calmar = (-50.0 / 1_000.0) / (200.0 / 1050.0)
    assert m.calmar == pytest.approx(expected_calmar)


@pytest.mark.parametrize("bad", [0.0, -1.0])
def test_compute_metrics_rejects_non_positive_equity(bad: float) -> None:
    with pytest.raises(ValueError):
        compute_metrics([1.0], initial_equity=bad, bars_per_year=24_000.0)


def test_compute_metrics_rejects_non_positive_bars_per_year() -> None:
    with pytest.raises(ValueError):
        compute_metrics([1.0], initial_equity=1_000.0, bars_per_year=0.0)
