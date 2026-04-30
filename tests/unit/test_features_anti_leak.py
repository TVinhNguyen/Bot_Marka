"""Issue #2: features must use only data strictly before the decision bar."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ai_mt5.data import build_features
from ai_mt5.domain.bar import Bar


def _bar(i: int, close: float) -> Bar:
    base = datetime(2026, 4, 29, 8, 0, tzinfo=UTC)
    t = base + timedelta(minutes=15 * i)
    return Bar(
        symbol="EURUSD",
        timeframe="M15",
        open_time=t,
        open=close - 0.0002,
        high=close + 0.0003,
        low=close - 0.0003,
        close=close,
        volume=1000.0,
    )


def test_features_use_history_only() -> None:
    history = [_bar(i, 1.07 + 0.0001 * i) for i in range(30)]
    decision = _bar(30, 1.0731)
    feats = build_features(history, decision)
    assert feats.n_bars_used == 30
    assert feats.last_close == pytest.approx(history[-1].close)
    assert feats.decision_time == decision.open_time.isoformat()


def test_features_reject_decision_bar_in_history() -> None:
    history = [_bar(i, 1.07 + 0.0001 * i) for i in range(5)]
    decision = history[-1]
    with pytest.raises(ValueError, match="look-ahead leakage"):
        build_features(history, decision)


def test_features_reject_future_bar_in_history() -> None:
    history = [_bar(i, 1.07 + 0.0001 * i) for i in range(5)]
    decision = _bar(2, 1.0702)  # decision before some history bars
    with pytest.raises(ValueError, match="look-ahead leakage"):
        build_features(history, decision)


def test_features_require_non_empty_history() -> None:
    with pytest.raises(ValueError, match="at least one"):
        build_features([], _bar(0, 1.07))
