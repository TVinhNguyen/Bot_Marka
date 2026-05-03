"""Offline Chronos-style quantile adapter."""

from __future__ import annotations

import math

from ..data.features import FeatureSet
from ..domain.forecast import Direction, Forecast
from ..utils.time_utils import utcnow
from .protocol import input_hash


class ChronosAdapter:
    """Deterministic Chronos-flavoured offline adapter that produces q10/q50/q90.

    The quantile spread is used as the uncertainty field; direction is
    derived from the sign of q50 (the median) with a dead-band.
    """

    name = "chronos"
    version = "mock-0.3.0"

    def __init__(self, *, horizon: int = 8, dead_band: float = 0.0005) -> None:
        if horizon <= 0:
            raise ValueError("horizon must be positive")
        if dead_band < 0:
            raise ValueError("dead_band must be non-negative")
        self._horizon = horizon
        self._dead_band = dead_band

    def forecast(
        self,
        features: FeatureSet,
        *,
        symbol: str,
        timeframe: str,
    ) -> Forecast:
        # Median projection: last return smoothed by sma gap sign.
        sma_gap = features.sma_5 - features.sma_20
        tilt = math.copysign(1.0, sma_gap) if sma_gap != 0 else 0.0
        q50 = features.return_5 * 0.5 + tilt * features.realized_vol_20 * 0.25
        spread = max(features.realized_vol_20 * 1.0, 1e-6)
        q10 = q50 - spread
        q90 = q50 + spread

        # Uncertainty: normalized quantile spread, capped to [0, 1].
        uncertainty = float(min(1.0, (q90 - q10) / (abs(q50) + 2 * spread + 1e-9)))

        direction: Direction
        if q50 > self._dead_band:
            direction = "BUY"
        elif q50 < -self._dead_band:
            direction = "SELL"
        else:
            direction = "HOLD"
        raw_score = float(q50 / spread)
        raw_score = float(max(min(raw_score, 5.0), -5.0))
        score = float(math.tanh(raw_score))
        if direction == "HOLD":
            raw_score = 0.0
            score = 0.0
        confidence = float(max(0.0, min(1.0, 1.0 - uncertainty)))

        return Forecast(
            model_name=self.name,
            symbol=symbol,
            timeframe=timeframe,
            horizon=self._horizon,
            direction=direction,
            expected_return=q50,
            uncertainty=uncertainty,
            raw_score=raw_score,
            score=score,
            confidence=confidence,
            reason=(
                f"chronos q10={q10:+.6f} q50={q50:+.6f} q90={q90:+.6f} dead_band={self._dead_band}"
            ),
            timestamp=utcnow(),
            metadata={
                "model_version": self.version,
                "horizon": self._horizon,
                "q10": q10,
                "q50": q50,
                "q90": q90,
                "input_hash": input_hash(features),
                "decision_time": features.decision_time,
            },
        )
