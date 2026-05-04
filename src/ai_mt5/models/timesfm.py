"""Offline TimesFM-style adapter.

The real TimesFM model is a pretrained foundation model for point
forecasts of returns/vol. It is not loaded here — we ship a deterministic
mock that (a) respects the :class:`ModelAdapter` contract, (b) produces
numerically sensible BUY/SELL/HOLD decisions from the shared
:class:`FeatureSet`, and (c) attaches pinned reproducibility metadata.

The mock extrapolates the last return in the direction of the 5-vs-20
SMA gap, scaled by a volatility-aware confidence.
"""

from __future__ import annotations

import math

from ..data.features import FeatureSet
from ..domain.forecast import Direction, Forecast
from ..utils.time_utils import utcnow
from .protocol import input_hash


class TimesFMAdapter:
    """Deterministic TimesFM-flavoured offline adapter."""

    name = "timesfm"
    version = "mock-0.1.0"

    def __init__(self, *, horizon: int = 4) -> None:
        if horizon <= 0:
            raise ValueError("horizon must be positive")
        self._horizon = horizon

    def forecast(
        self,
        features: FeatureSet,
        *,
        symbol: str,
        timeframe: str,
    ) -> Forecast:
        sma_gap = features.sma_5 - features.sma_20
        vol = max(features.realized_vol_20, 1e-6)
        # Project an expected return: direction from sma gap, magnitude from
        # recent realized return dampened by vol.
        scale = abs(sma_gap) / (abs(sma_gap) + vol)
        expected_return = math.copysign(1.0, sma_gap) * abs(features.return_5) * scale
        raw_score = float(max(min(expected_return / vol, 5.0), -5.0))
        score = math.tanh(raw_score)

        direction: Direction
        if score > 0.15:
            direction = "BUY"
        elif score < -0.15:
            direction = "SELL"
        else:
            direction = "HOLD"
            raw_score = 0.0
            score = 0.0

        confidence = min(1.0, abs(score))
        uncertainty = float(max(0.0, min(1.0, 1.0 - confidence)))

        return Forecast(
            model_name=self.name,
            symbol=symbol,
            timeframe=timeframe,
            horizon=self._horizon,
            direction=direction,
            expected_return=float(expected_return),
            uncertainty=uncertainty,
            raw_score=raw_score,
            score=float(score),
            confidence=float(confidence),
            reason=f"timesfm sma_gap={sma_gap:+.6f} vol={vol:.6f}",
            timestamp=utcnow(),
            metadata={
                "model_version": self.version,
                "horizon": self._horizon,
                "input_hash": input_hash(features),
                "decision_time": features.decision_time,
                "n_bars_used": features.n_bars_used,
            },
        )
