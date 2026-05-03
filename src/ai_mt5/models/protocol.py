"""Shared Model Adapter protocol and helpers.

Every adapter must:

* expose ``name`` (stable, human-readable) and ``version`` (pinned
  revision string) so persisted Forecasts can be re-evaluated later;
* implement ``forecast(features, *, symbol, timeframe) -> Forecast`` that
  returns a valid :class:`~ai_mt5.domain.forecast.Forecast`;
* raise :class:`AdapterError` on any recoverable failure so the
  ensemble can mark the component as failed without crashing the tick.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Protocol, runtime_checkable

from ..data.features import FeatureSet
from ..domain.forecast import Forecast


class AdapterError(RuntimeError):
    """Raised by a Model Adapter when it cannot produce a Forecast."""


@runtime_checkable
class ModelAdapter(Protocol):
    """Offline Model Adapter contract.

    Real adapters (TimesFM, Kronos, Chronos weights on disk) will subclass
    this; the offline shipments here are deterministic mocks used for
    evaluation-report tests and Ensemble plumbing.
    """

    name: str
    version: str

    def forecast(
        self,
        features: FeatureSet,
        *,
        symbol: str,
        timeframe: str,
    ) -> Forecast: ...


def input_hash(features: FeatureSet) -> str:
    """Stable 16-char hex hash of a :class:`FeatureSet`.

    Persisted alongside every Forecast so later runs can prove they saw
    the same input (reproducibility metadata per issue #7 acceptance
    criteria).
    """
    payload = json.dumps(asdict(features), sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
