"""SMA-momentum Baseline adapter.

Behavior:

* If ``sma_5 > sma_20`` and ``return_5 > 0`` -> ``BUY`` with positive score.
* If ``sma_5 < sma_20`` and ``return_5 < 0`` -> ``SELL`` with negative score.
* Otherwise -> ``HOLD`` with score 0.

The adapter never reads bars from disk or talks to MT5; it only consumes a
:class:`FeatureSet` so that every forecast is reproducible from the same
inputs (anti-leak by construction).
"""

from __future__ import annotations

import math

from ..data.features import FeatureSet
from ..domain.forecast import Direction, Forecast
from ..utils.time_utils import utcnow


class BaselineAdapter:
    """Deterministic Baseline model adapter."""

    name = "baseline_sma_momentum"
    version = "1.0.0"

    def __init__(self, *, horizon: int = 8, score_scale: float = 50.0) -> None:
        if horizon <= 0:
            raise ValueError("horizon must be positive")
        if score_scale <= 0:
            raise ValueError("score_scale must be positive")
        self._horizon = horizon
        self._score_scale = score_scale

    def forecast(
        self,
        features: FeatureSet,
        *,
        symbol: str,
        timeframe: str,
    ) -> Forecast:
        sma_diff = features.sma_5 - features.sma_20
        # Normalize SMA gap by realized vol (with a floor so we never divide by 0).
        vol_floor = max(features.realized_vol_20, 1e-6)
        normalized = sma_diff / (vol_floor * self._score_scale)
        # Clip the raw_score to a sane range and squash to [-1, 1] for ``score``.
        raw_score = float(max(min(normalized, 5.0), -5.0))
        score = math.tanh(raw_score)

        direction: Direction
        if features.sma_5 > features.sma_20 and features.return_5 > 0:
            direction = "BUY"
        elif features.sma_5 < features.sma_20 and features.return_5 < 0:
            direction = "SELL"
        else:
            direction = "HOLD"
            raw_score = 0.0
            score = 0.0

        # Confidence grows with |score| but is dampened by recent volatility.
        confidence = min(1.0, abs(score) / (1.0 + 5.0 * features.realized_vol_20))
        uncertainty = float(max(0.0, min(1.0, 1.0 - confidence)))

        return Forecast(
            model_name=self.name,
            symbol=symbol,
            timeframe=timeframe,
            horizon=self._horizon,
            direction=direction,
            expected_return=features.return_5,
            uncertainty=uncertainty,
            raw_score=raw_score,
            score=float(score),
            confidence=float(confidence),
            reason=(
                f"sma_5={features.sma_5:.5f} sma_20={features.sma_20:.5f} "
                f"return_5={features.return_5:.5f}"
            ),
            timestamp=utcnow(),
            metadata={
                "decision_time": features.decision_time,
                "n_bars_used": features.n_bars_used,
                "score_scale": self._score_scale,
            },
        )
