"""Issue #4: SL/TP respects ATR, RR, and broker stop level."""

from __future__ import annotations

import pytest

from ai_mt5.risk.stops import compute_sl_tp


@pytest.fixture
def kwargs() -> dict:
    return dict(
        side="BUY",
        entry_price=1.07490,
        atr=0.0010,
        sl_atr_min=1.2,
        sl_atr_max=2.5,
        tp_atr=2.0,
        rr_min=1.0,
        stop_level_points=10,
        point_size=0.00001,
    )


def test_buy_places_sl_below_and_tp_above(kwargs) -> None:
    res = compute_sl_tp(**kwargs)
    assert res.approved
    assert res.sl < kwargs["entry_price"] < res.tp


def test_sell_places_sl_above_and_tp_below(kwargs) -> None:
    res = compute_sl_tp(**{**kwargs, "side": "SELL"})
    assert res.approved
    assert res.tp < kwargs["entry_price"] < res.sl


def test_rr_min_is_enforced(kwargs) -> None:
    res = compute_sl_tp(**{**kwargs, "rr_min": 3.0, "tp_atr": 0.5})
    assert res.approved
    rr = abs(res.tp - kwargs["entry_price"]) / res.sl_distance_price
    assert rr >= 3.0 - 1e-9


def test_zero_atr_rejects(kwargs) -> None:
    res = compute_sl_tp(**{**kwargs, "atr": 0.0})
    assert not res.approved
    assert "invalid_atr" in res.rejected_by


def test_invalid_side_rejects(kwargs) -> None:
    res = compute_sl_tp(**{**kwargs, "side": "FLAT"})
    assert not res.approved


def test_broker_stop_level_floor(kwargs) -> None:
    """When the broker stop level exceeds sl_atr_max*ATR, the result rejects."""
    res = compute_sl_tp(
        **{
            **kwargs,
            "atr": 0.00001,
            "sl_atr_max": 1.5,
            "stop_level_points": 1000,  # 1000 * 0.00001 = 0.01 >> 0.000015
        }
    )
    assert not res.approved
    assert "sl_below_broker_stop_level" in res.rejected_by
