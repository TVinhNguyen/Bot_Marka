"""Cost model arithmetic must match the broker friction definitions exactly."""

from __future__ import annotations

import pytest

from ai_mt5.backtest import CostModel


def test_entry_cost_matches_slippage_only() -> None:
    cm = CostModel(
        spread_points=2.0,
        commission_per_lot=7.0,
        slippage_buffer_points=1.5,
        point_size=0.0001,
        contract_size=100_000.0,
    )
    # entry only charges slippage_buffer; spread + commission live on exit
    expected = 1.5 * 0.0001 * 100_000.0 * 0.5
    assert cm.entry_cost(volume=0.5) == pytest.approx(expected)


def test_exit_cost_includes_spread_slippage_commission() -> None:
    cm = CostModel(
        spread_points=2.0,
        commission_per_lot=7.0,
        slippage_buffer_points=1.5,
        point_size=0.0001,
        contract_size=100_000.0,
    )
    spread = 2.0 * 0.0001 * 100_000.0 * 0.5
    slip = 1.5 * 0.0001 * 100_000.0 * 0.5
    commission = 7.0 * 0.5
    assert cm.exit_cost(volume=0.5) == pytest.approx(spread + slip + commission)


def test_holding_cost_uses_per_side_swap() -> None:
    cm = CostModel(
        swap_long_per_night=-1.0,  # favourable
        swap_short_per_night=2.0,  # punitive
    )
    assert cm.holding_cost(side="BUY", volume=1.0, n_nights=3) == pytest.approx(-3.0)
    assert cm.holding_cost(side="SELL", volume=2.0, n_nights=2) == pytest.approx(8.0)


def test_holding_cost_zero_when_intraday() -> None:
    cm = CostModel(swap_long_per_night=10.0, swap_short_per_night=10.0)
    assert cm.holding_cost(side="BUY", volume=1.0, n_nights=0) == 0.0


def test_total_cost_is_sum_of_parts() -> None:
    cm = CostModel(
        spread_points=2.0,
        commission_per_lot=7.0,
        slippage_buffer_points=1.5,
        swap_short_per_night=2.0,
    )
    expected = (
        cm.entry_cost(volume=0.5)
        + cm.exit_cost(volume=0.5)
        + cm.holding_cost(side="SELL", volume=0.5, n_nights=2)
    )
    assert cm.total_cost(side="SELL", volume=0.5, n_nights=2) == pytest.approx(expected)


def test_zero_volume_returns_zero() -> None:
    cm = CostModel(spread_points=10.0, commission_per_lot=10.0, slippage_buffer_points=10.0)
    assert cm.entry_cost(0.0) == 0.0
    assert cm.exit_cost(0.0) == 0.0
    assert cm.holding_cost(side="BUY", volume=0.0, n_nights=5) == 0.0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"point_size": 0.0},
        {"contract_size": -1.0},
        {"spread_points": -1.0},
        {"commission_per_lot": -1.0},
        {"slippage_buffer_points": -1.0},
    ],
)
def test_invalid_inputs_rejected(kwargs: dict[str, float]) -> None:
    base = {
        "point_size": 0.0001,
        "contract_size": 100_000.0,
        "spread_points": 0.0,
        "commission_per_lot": 0.0,
        "slippage_buffer_points": 0.0,
    }
    base.update(kwargs)
    with pytest.raises(ValueError):
        CostModel(**base)


def test_holding_cost_rejects_unknown_side() -> None:
    cm = CostModel()
    with pytest.raises(ValueError):
        cm.holding_cost(side="HOLD", volume=1.0, n_nights=1)
