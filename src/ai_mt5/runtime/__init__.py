"""Runtime mode plumbing, promotion gates, and shadow-mode reporting.

This package implements the operational path for issue #11:

* :class:`RuntimeMode` — the canonical environment ladder
  ``dev -> dry_run -> shadow -> demo -> staging -> small_live``.
* :func:`runtime_snapshot` — captures the commit SHA + config hash for
  rollback bookkeeping. Embedded in ``tick.start`` audit records and in
  promotion-check reports.
* :func:`run_promotion_checks` — runs the documented checklist before
  promoting to demo / staging / small_live.
* :func:`build_shadow_report` — compares Shadow Mode risk decisions to
  the realised market direction over the next ``horizon`` bars.

The package is deliberately decoupled from MT5 so it stays unit-testable
and so the CI can run promotion checks without a broker connection.
"""

from .modes import RuntimeMode, allows_order_send, is_live_capable, parse_mode
from .promotion import (
    PromotionCheckOutcome,
    PromotionReport,
    run_promotion_checks,
)
from .shadow_report import (
    ShadowDecisionOutcome,
    ShadowReport,
    build_shadow_report,
)
from .snapshot import RuntimeSnapshot, runtime_snapshot

__all__ = [
    "PromotionCheckOutcome",
    "PromotionReport",
    "RuntimeMode",
    "RuntimeSnapshot",
    "ShadowDecisionOutcome",
    "ShadowReport",
    "allows_order_send",
    "build_shadow_report",
    "is_live_capable",
    "parse_mode",
    "run_promotion_checks",
    "runtime_snapshot",
]
