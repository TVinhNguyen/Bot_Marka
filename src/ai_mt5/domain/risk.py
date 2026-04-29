"""Risk Decision contract: the hard gate between Meta-Signals and the Executor."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Side = Literal["BUY", "SELL"]


@dataclass(frozen=True)
class RiskDecision:
    """The Risk manager's explicit approve / reject of a Meta-Signal.

    Approved decisions carry the broker-valid sizing inputs (side, volume,
    SL, TP, magic, comment) so the Executor can build an order request
    without re-reading any config. Rejected decisions carry every applicable
    rejection reason for auditability.
    """

    approved: bool
    side: Side | None
    volume: float
    sl: float | None
    tp: float | None
    magic: int
    comment: str
    reason: str
    rejected_by: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.approved:
            if self.side is None:
                raise ValueError("approved RiskDecision must have a side")
            if self.volume <= 0:
                raise ValueError("approved RiskDecision must have positive volume")
            if self.sl is None or self.tp is None:
                raise ValueError("approved RiskDecision must have SL and TP")
            if self.rejected_by:
                raise ValueError("approved RiskDecision must not list rejection reasons")
        else:
            if self.volume != 0.0:
                raise ValueError("rejected RiskDecision must have volume=0")
            if not self.rejected_by:
                raise ValueError("rejected RiskDecision must list at least one reason")

    @classmethod
    def reject(
        cls,
        reasons: list[str],
        *,
        magic: int,
        comment: str,
        reason: str = "rejected by risk gate",
    ) -> RiskDecision:
        """Convenience constructor for a rejected decision."""
        return cls(
            approved=False,
            side=None,
            volume=0.0,
            sl=None,
            tp=None,
            magic=magic,
            comment=comment,
            reason=reason,
            rejected_by=list(reasons),
        )
