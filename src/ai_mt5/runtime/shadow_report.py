"""Issue #11 — Shadow Mode reporting.

Shadow Mode runs the full pipeline against live data without firing
``order_send``. The decisions are written to the audit JSONL with the
``signal_direction`` and ``decision_time`` (the bar open time).

This module reads that audit trail back and joins each Shadow decision
to the subsequent ``horizon`` Closed Bars to produce a comparison with
the *realised* market direction:

* ``BUY`` decision and bar ``[t+horizon].close > [t].close``        => agreement.
* ``SELL`` decision and bar ``[t+horizon].close < [t].close``        => agreement.
* ``HOLD`` decisions are excluded from the agreement statistics — a
  HOLD that happened to be "right" tells us nothing about the model.

The output is intentionally minimal: per-decision outcomes plus a
single summary structure with counts, accuracy, and a coverage ratio
(how many decisions had enough future bars to score). It is not a
backtest replacement; it is a sanity check that Shadow decisions are
not directionally random before promotion.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ai_mt5.domain.bar import Bar


@dataclass(frozen=True)
class ShadowDecisionOutcome:
    """One audited Shadow decision joined with its realised outcome."""

    decision_time: datetime
    symbol: str
    timeframe: str
    decision_direction: str  # "BUY" | "SELL" | "HOLD"
    realised_direction: str | None  # "UP" | "DOWN" | "FLAT" | None when no future bars
    agreed: bool | None  # None when realised_direction is None or decision is HOLD
    horizon_bars: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_time": self.decision_time.isoformat(),
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "decision_direction": self.decision_direction,
            "realised_direction": self.realised_direction,
            "agreed": self.agreed,
            "horizon_bars": self.horizon_bars,
        }


@dataclass(frozen=True)
class ShadowReport:
    """Aggregate Shadow Mode comparison."""

    horizon_bars: int
    n_decisions: int
    n_directional: int  # excludes HOLD
    n_scored: int  # decisions that had enough future bars
    n_agreed: int
    outcomes: tuple[ShadowDecisionOutcome, ...] = field(default_factory=tuple)

    @property
    def accuracy(self) -> float | None:
        if self.n_scored == 0:
            return None
        return self.n_agreed / self.n_scored

    @property
    def coverage(self) -> float | None:
        """Fraction of directional decisions that were scored."""
        if self.n_directional == 0:
            return None
        return self.n_scored / self.n_directional

    def to_dict(self) -> dict[str, Any]:
        return {
            "horizon_bars": self.horizon_bars,
            "n_decisions": self.n_decisions,
            "n_directional": self.n_directional,
            "n_scored": self.n_scored,
            "n_agreed": self.n_agreed,
            "accuracy": self.accuracy,
            "coverage": self.coverage,
            "outcomes": [o.to_dict() for o in self.outcomes],
        }


def build_shadow_report(
    *,
    audit_path: Path,
    bars: Iterable[Bar],
    horizon_bars: int = 4,
    flat_eps: float = 0.0,
    symbol: str | None = None,
    timeframe: str | None = None,
) -> ShadowReport:
    """Read ``audit_path``, join decisions with future bars, summarise.

    Parameters
    ----------
    audit_path:
        Path to the audit JSONL written by :class:`TickRunner`.
    bars:
        Closed Bars covering the audit period (and ``horizon_bars``
        beyond the last decision so it can be scored).
    horizon_bars:
        How many bars after the decision bar to use for the realised
        direction. Default 4.
    flat_eps:
        Absolute price-difference threshold below which the realised
        move is treated as ``FLAT``. Default 0.0 (any non-zero move
        counts).
    symbol / timeframe:
        Optional filters; if set, only decisions for this
        symbol-timeframe are scored.
    """
    if horizon_bars < 1:
        raise ValueError("horizon_bars must be >= 1")
    bar_list = sorted(bars, key=lambda b: b.open_time)
    bars_by_time: dict[datetime, int] = {b.open_time: i for i, b in enumerate(bar_list)}
    decisions = list(_read_shadow_decisions(audit_path, symbol=symbol, timeframe=timeframe))

    outcomes: list[ShadowDecisionOutcome] = []
    n_directional = 0
    n_scored = 0
    n_agreed = 0

    for d in decisions:
        idx = bars_by_time.get(d["decision_time"])
        decision_dir = d["direction"]
        future_idx = (idx + horizon_bars) if idx is not None else None
        realised: str | None = None
        agreed: bool | None = None
        if future_idx is not None and idx is not None and 0 <= future_idx < len(bar_list):
            delta = bar_list[future_idx].close - bar_list[idx].close
            if abs(delta) <= flat_eps:
                realised = "FLAT"
            elif delta > 0:
                realised = "UP"
            else:
                realised = "DOWN"
        if decision_dir != "HOLD":
            n_directional += 1
        if realised is not None and decision_dir != "HOLD" and realised != "FLAT":
            agreed = (decision_dir == "BUY" and realised == "UP") or (
                decision_dir == "SELL" and realised == "DOWN"
            )
            n_scored += 1
            if agreed:
                n_agreed += 1
        outcomes.append(
            ShadowDecisionOutcome(
                decision_time=d["decision_time"],
                symbol=d["symbol"],
                timeframe=d["timeframe"],
                decision_direction=decision_dir,
                realised_direction=realised,
                agreed=agreed,
                horizon_bars=horizon_bars,
            )
        )
    return ShadowReport(
        horizon_bars=horizon_bars,
        n_decisions=len(outcomes),
        n_directional=n_directional,
        n_scored=n_scored,
        n_agreed=n_agreed,
        outcomes=tuple(outcomes),
    )


def _read_shadow_decisions(
    path: Path, *, symbol: str | None, timeframe: str | None
) -> Iterable[dict[str, Any]]:
    """Yield ``{decision_time, direction, symbol, timeframe}`` per Shadow tick.

    A "Shadow decision" is reconstructed by joining the ``tick.start``
    record (which carries the runtime mode + symbol-timeframe + bar
    open_time) with the immediately following ``meta_signal`` /
    ``risk_decision`` records that share the same ``trace_id``. We only
    emit when ``mode == "shadow"`` so this function is safe to point
    at any operator audit trail.
    """
    if not path.exists():
        return
    pending: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = rec.get("kind")
            trace_id = rec.get("trace_id")
            payload = rec.get("payload", {})
            if not trace_id:
                continue
            if kind == "tick.start" and payload.get("mode") == "shadow":
                pending[trace_id] = {
                    "symbol": payload.get("symbol", ""),
                    "timeframe": payload.get("timeframe", ""),
                }
            elif kind == "tick.success" and trace_id in pending:
                ctx = pending.pop(trace_id)
                if symbol and ctx["symbol"] != symbol:
                    continue
                if timeframe and ctx["timeframe"] != timeframe:
                    continue
                decision_time_raw = payload.get("decision_time")
                direction = payload.get("signal_direction") or payload.get("direction")
                if not decision_time_raw or direction is None:
                    continue
                yield {
                    "decision_time": _parse_iso(decision_time_raw),
                    "direction": str(direction),
                    "symbol": ctx["symbol"],
                    "timeframe": ctx["timeframe"],
                }


def _parse_iso(value: str) -> datetime:
    # ``datetime.fromisoformat`` accepts the audit format we emit
    # (``...+00:00``); raise loudly on anything else so we never
    # silently drop decisions.
    return datetime.fromisoformat(value)


__all__ = ["ShadowDecisionOutcome", "ShadowReport", "build_shadow_report"]
