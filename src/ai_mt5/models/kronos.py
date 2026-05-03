"""Offline Kronos-style momentum adapter with pinned metadata."""

from __future__ import annotations

import math

from ..data.features import FeatureSet
from ..domain.forecast import Direction, Forecast
from ..utils.time_utils import utcnow
from .protocol import input_hash


class KronosAdapter:
    """Deterministic Kronos-flavoured offline adapter.

    Uses the 5-bar momentum over an SMA regime filter:

    * regime = ``sign(sma_5 - sma_20)``
    * signal = ``regime * tanh(momentum_5 / price_scale)``

    Direction is taken from the signal's sign above a configurable
    dead-band so tiny signals stay HOLD.
    """

    name = "kronos"
    version = "mock-0.2.0"

    def __init__(
        self,
        *,
        horizon: int = 6,
        dead_band: float = 0.1,
        price_scale: float = 0.0005,
    ) -> None:
        if horizon <= 0:
            raise ValueError("horizon must be positive")
        if dead_band < 0 or dead_band >= 1:
            raise ValueError("dead_band must be in [0, 1)")
        if price_scale <= 0:
            raise ValueError("price_scale must be positive")
        self._horizon = horizon
        self._dead_band = dead_band
        self._price_scale = price_scale

    def forecast(
        self,
        features: FeatureSet,
        *,
        symbol: str,
        timeframe: str,
    ) -> Forecast:
        regime = 0.0
        if features.sma_5 > features.sma_20:
            regime = 1.0
        elif features.sma_5 < features.sma_20:
            regime = -1.0
        momentum = features.momentum_5 / self._price_scale
        # Regime acts as an agreement gate: only signal when the short-term
        # momentum and the SMA regime point the same way.
        aligned = regime != 0.0 and ((regime > 0 and momentum > 0) or (regime < 0 and momentum < 0))
        raw = math.tanh(momentum) if aligned else 0.0
        raw_score = float(max(min(raw * 3.0, 5.0), -5.0))
        score = float(math.tanh(raw_score))

        direction: Direction
        if score > self._dead_band:
            direction = "BUY"
        elif score < -self._dead_band:
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
            expected_return=features.return_5,
            uncertainty=uncertainty,
            raw_score=raw_score,
            score=score,
            confidence=float(confidence),
            reason=(
                f"kronos regime={int(regime):+d} momentum_5={features.momentum_5:+.6f} "
                f"dead_band={self._dead_band}"
            ),
            timestamp=utcnow(),
            metadata={
                "model_version": self.version,
                "horizon": self._horizon,
                "dead_band": self._dead_band,
                "price_scale": self._price_scale,
                "input_hash": input_hash(features),
                "decision_time": features.decision_time,
            },
        )
