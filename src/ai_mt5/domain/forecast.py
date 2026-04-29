"""Forecast and MetaSignal contracts shared by every model adapter and the ensemble."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

Direction = Literal["BUY", "SELL", "HOLD"]


@dataclass(frozen=True)
class Forecast:
    """A model-specific prediction.

    Per the domain rules in CONTEXT.md, a Forecast describes future market
    behavior; it never carries sizing, SL/TP, or order intent. Only the
    Ensemble may turn one or more Forecasts into a :class:`MetaSignal`.
    """

    model_name: str
    symbol: str
    timeframe: str
    horizon: int
    direction: Direction
    expected_return: float
    uncertainty: float
    raw_score: float
    score: float
    confidence: float
    reason: str
    timestamp: datetime
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.horizon <= 0:
            raise ValueError("Forecast.horizon must be positive")
        if self.uncertainty < 0.0 or self.uncertainty > 1.0:
            raise ValueError("Forecast.uncertainty must be in [0, 1]")
        if self.confidence < 0.0 or self.confidence > 1.0:
            raise ValueError("Forecast.confidence must be in [0, 1]")
        if self.timestamp.tzinfo is None:
            raise ValueError("Forecast.timestamp must be timezone-aware (UTC)")


@dataclass(frozen=True)
class MetaSignal:
    """The cost-aware ensemble output. Decides BUY/SELL/HOLD before risk sizing."""

    direction: Direction
    final_score: float
    raw_score: float
    agreement: float
    confidence: float
    cost_penalty: float = 0.0
    uncertainty_penalty: float = 0.0
    event_penalty: float = 0.0
    veto_reasons: list[str] = field(default_factory=list)
    reason: str = ""
    components: dict[str, Forecast] = field(default_factory=dict)
    timestamp: datetime | None = None

    def is_actionable(self) -> bool:
        return self.direction in ("BUY", "SELL") and not self.veto_reasons
