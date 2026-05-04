"""Time-series Model Adapters (issue #7).

All adapters here are *offline* — they consume a :class:`FeatureSet` (which
is built from Closed Bars only) and return the shared
:class:`~ai_mt5.domain.forecast.Forecast` contract. No adapter talks to MT5
or requests live data; production inference will swap in real model
weights behind the same :class:`ModelAdapter` protocol.
"""

from .chronos import ChronosAdapter
from .evaluation import EvaluationReport, evaluate_adapter
from .kronos import KronosAdapter
from .protocol import AdapterError, ModelAdapter, input_hash
from .timesfm import TimesFMAdapter

__all__ = [
    "AdapterError",
    "ChronosAdapter",
    "EvaluationReport",
    "KronosAdapter",
    "ModelAdapter",
    "TimesFMAdapter",
    "evaluate_adapter",
    "input_hash",
]
