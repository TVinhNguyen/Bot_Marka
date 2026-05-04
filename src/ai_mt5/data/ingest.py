"""Ingest Closed Bars into the :class:`BarStore` after quality gates.

The ingest function is the gatekeeper between "raw data we just received"
and "data the tick runner can act on". It is deliberately thin:

1. Run :func:`run_quality_gates` on the input.
2. If a *core* gate is blocking, return without writing; caller logs.
3. Otherwise append to the store and return the final
   :class:`QualityReport` (warnings preserved).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..domain.bar import Bar
from .bar_store import BarStore
from .quality import QualityConfig, QualityReport, run_quality_gates


@dataclass(frozen=True)
class IngestResult:
    """Outcome of a single ingest call."""

    report: QualityReport
    bars_written: int
    blocked: bool

    @property
    def ok(self) -> bool:
        """True iff nothing blocked; warnings are allowed."""
        return not self.blocked


def ingest_bars(
    bars: list[Bar],
    *,
    store: BarStore,
    symbol: str,
    timeframe: str,
    config: QualityConfig | None = None,
) -> IngestResult:
    """Run quality gates and, if non-blocking, append to ``store``."""
    report = run_quality_gates(bars, symbol=symbol, timeframe=timeframe, config=config)
    if not report.ok:
        return IngestResult(report=report, bars_written=0, blocked=True)
    written = store.append_many(bars)
    return IngestResult(report=report, bars_written=written, blocked=False)
