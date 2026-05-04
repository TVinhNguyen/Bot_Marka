"""Issue #4: position sizing invariants and broker constraints."""

from __future__ import annotations

import math

import pytest

from ai_mt5.risk.position_sizing import _round_to_step, size_position


def test_round_to_step_is_decimal_exact() -> None:
    """0.29 / 0.01 is 28.999... in IEEE-754; ensure we still floor to 0.29."""
    assert _round_to_step(0.29, 0.01) == pytest.approx(0.29, abs=1e-12)
    assert _round_to_step(0.30, 0.01) == pytest.approx(0.30, abs=1e-12)
    assert _round_to_step(0.305, 0.01) == pytest.approx(0.30, abs=1e-12)
    assert _round_to_step(0.07, 0.01) == pytest.approx(0.07, abs=1e-12)
    # 0.7 / 0.1 is also affected by IEEE-754 (= 6.999...).
    assert _round_to_step(0.7, 0.1) == pytest.approx(0.7, abs=1e-12)


@pytest.fixture
def base_kwargs() -> dict[str, float]:
    return dict(
        equity=10_000.0,
        base_risk_pct=0.002,
        min_risk_pct=0.0005,
        max_risk_pct=0.005,
        sl_distance_price=0.0010,
        contract_size=100_000.0,
        volume_min=0.01,
        volume_max=50.0,
        volume_step=0.01,
    )


def test_volume_is_step_aligned(base_kwargs) -> None:
    res = size_position(**base_kwargs)
    assert res.approved
    assert math.isclose(round(res.volume / 0.01) * 0.01, res.volume, abs_tol=1e-9)


def test_actual_risk_does_not_exceed_max_cap(base_kwargs) -> None:
    res = size_position(**base_kwargs)
    assert res.risk_amount <= base_kwargs["equity"] * base_kwargs["max_risk_pct"]


def test_too_small_account_rejects_below_min_volume(base_kwargs) -> None:
    res = size_position(**{**base_kwargs, "equity": 10.0})
    assert not res.approved
    assert "volume_below_min" in res.rejected_by or "risk_below_min_cap" in res.rejected_by


def test_zero_sl_distance_rejects(base_kwargs) -> None:
    res = size_position(**{**base_kwargs, "sl_distance_price": 0.0})
    assert not res.approved
    assert "invalid_sl_distance" in res.rejected_by


def test_volume_capped_to_volume_max(base_kwargs) -> None:
    """A small base_risk_pct with a tight volume_max must clamp volume."""
    res = size_position(
        **{
            **base_kwargs,
            "equity": 1_000_000.0,
            "base_risk_pct": 0.05,
            "max_risk_pct": 0.5,
            "min_risk_pct": 0.0001,
            "volume_max": 1.0,
        }
    )
    assert res.approved
    assert res.volume == pytest.approx(1.0, abs=1e-6)


def test_volume_max_below_step_rejects_with_reason() -> None:
    """volume_max < volume_step must reject explicitly, never return volume=0 silently."""
    res = size_position(
        equity=10_000.0,
        base_risk_pct=0.002,
        min_risk_pct=0.0005,
        max_risk_pct=0.005,
        sl_distance_price=0.0010,
        contract_size=100_000.0,
        volume_min=0.01,
        volume_max=0.005,  # smaller than volume_step
        volume_step=0.01,
    )
    assert not res.approved
    assert res.rejected_by, "rejected SizingResult must list at least one reason"


def test_risk_exceeds_max_cap_after_step_rounding() -> None:
    """If even the smallest stepped volume puts realized risk above the cap, reject."""
    # equity=1000, max_risk_pct=0.0001 -> max risk = $0.10
    # smallest volume 0.01 * sl_distance 0.001 * contract 100_000 = $1 risk -> exceeds.
    res = size_position(
        equity=1_000.0,
        base_risk_pct=0.00005,
        min_risk_pct=0.00001,
        max_risk_pct=0.0001,
        sl_distance_price=0.001,
        contract_size=100_000.0,
        volume_min=0.01,
        volume_max=50.0,
        volume_step=0.01,
    )
    assert not res.approved
    assert any(r in res.rejected_by for r in ("risk_exceeds_max_cap", "volume_below_min"))


def test_confidence_factor_scales_volume_down(base_kwargs) -> None:
    """A weaker signal must size smaller than a perfect one."""
    strong = size_position(**base_kwargs, confidence_factor=1.0)
    weak = size_position(**base_kwargs, confidence_factor=0.5)
    assert strong.approved and weak.approved
    assert weak.volume < strong.volume
    assert weak.effective_risk_pct < strong.effective_risk_pct
    assert weak.confidence_factor == pytest.approx(0.5)


def test_confidence_factor_one_matches_legacy_sizing(base_kwargs) -> None:
    legacy = size_position(**base_kwargs)
    full = size_position(**base_kwargs, confidence_factor=1.0)
    assert legacy.volume == full.volume
    assert legacy.risk_amount == pytest.approx(full.risk_amount)


def test_confidence_factor_clamps_to_min_risk_pct(base_kwargs) -> None:
    """confidence_factor=0 must floor to min_risk_pct, not zero out the trade."""
    res = size_position(**base_kwargs, confidence_factor=0.0)
    if res.approved:
        # With min_risk_pct floor, risk_amount must equal exactly min_risk_pct * equity
        # (modulo broker step rounding).
        assert res.effective_risk_pct == pytest.approx(base_kwargs["min_risk_pct"])
    else:
        # Or, if even the floor cannot be met by the broker step, reject cleanly.
        assert res.rejected_by


def test_confidence_factor_out_of_range_rejects(base_kwargs) -> None:
    above = size_position(**base_kwargs, confidence_factor=1.5)
    below = size_position(**base_kwargs, confidence_factor=-0.1)
    assert "invalid_confidence_factor" in above.rejected_by
    assert "invalid_confidence_factor" in below.rejected_by


def test_confidence_factor_never_exceeds_max_cap(base_kwargs) -> None:
    """Even with confidence_factor=1, the max_risk_pct cap must hold."""
    res = size_position(**{**base_kwargs, "base_risk_pct": 0.005}, confidence_factor=1.0)
    assert res.approved
    assert res.risk_amount <= base_kwargs["equity"] * base_kwargs["max_risk_pct"] + 1e-6
