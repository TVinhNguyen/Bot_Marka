"""Baseline model adapter.

A deterministic SMA-momentum control strategy used to prove whether the
AI ensemble adds value after costs. It produces a :class:`Forecast` using
the shared contract; it must never size, route, or execute trades.
"""

from .adapter import BaselineAdapter

__all__ = ["BaselineAdapter"]
