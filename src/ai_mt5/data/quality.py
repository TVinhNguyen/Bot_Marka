"""Market-data quality gates.

Given a series of :class:`~ai_mt5.domain.bar.Bar` objects for one
symbol-timeframe, the gates below return a structured
:class:`QualityReport` that downstream code (ingest, tick runner,
health endpoint) can reason about without re-walking the data.

Design rules (per issue #6):

* **Core** checks (UTC alignment, strictly-increasing timestamps, continuity
  within tolerance) fail *hard*. They block ingestion and trading for that
  symbol-timeframe.
* **Optional** checks (abnormal spread, zero volume, outlier returns) fail
  *soft*. They degrade the data to ``with_warnings`` but do not block.

The thresholds are configurable through :class:`QualityConfig` so later
slices can tune them per symbol without touching the gate code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from itertools import pairwise
from statistics import median

from ..domain.bar import Bar
from .timeframe import timeframe_delta


class QualitySeverity(StrEnum):
    """How bad a :class:`QualityIssue` is."""

    WARNING = "warning"
    BLOCKING = "blocking"


@dataclass(frozen=True)
class QualityIssue:
    """A single quality problem found in a bar series."""

    code: str
    severity: QualitySeverity
    message: str
    at: datetime | None = None


@dataclass(frozen=True)
class QualityReport:
    """Outcome of running every gate over a bar series."""

    symbol: str
    timeframe: str
    n_bars: int
    issues: list[QualityIssue] = field(default_factory=list)

    @property
    def blocking_issues(self) -> list[QualityIssue]:
        return [i for i in self.issues if i.severity is QualitySeverity.BLOCKING]

    @property
    def warnings(self) -> list[QualityIssue]:
        return [i for i in self.issues if i.severity is QualitySeverity.WARNING]

    @property
    def ok(self) -> bool:
        """True iff no blocking issues (warnings allowed)."""
        return not self.blocking_issues


@dataclass(frozen=True)
class QualityConfig:
    """Thresholds for the optional / soft quality checks."""

    # Abs return >= this many *median abs returns* is considered an outlier.
    return_outlier_mad_multiple: float = 8.0
    # Minimum sample size before we try to flag return outliers at all.
    return_outlier_min_samples: int = 20
    # Gap tolerance when counting missing bars: any gap > (1 + tol) * dt is
    # treated as a missing bar.  Defaults to 10%.
    gap_tolerance: float = 0.1
    # Symbol-specific spread ceilings; the gate is skipped when the symbol
    # is not in the mapping.
    spread_max_points: dict[str, int] = field(default_factory=dict)

    def resolve_spread_max(self, symbol: str) -> int | None:
        return self.spread_max_points.get(symbol)


# --- individual gates -------------------------------------------------------


def _check_timestamps(bars: list[Bar]) -> list[QualityIssue]:
    """UTC alignment + strict monotonicity."""
    issues: list[QualityIssue] = []
    for bar in bars:
        if bar.open_time.tzinfo is None:
            issues.append(
                QualityIssue(
                    code="naive_timestamp",
                    severity=QualitySeverity.BLOCKING,
                    message=f"bar at {bar.open_time} is not timezone-aware",
                    at=bar.open_time,
                )
            )
    for prev, cur in pairwise(bars):
        if cur.open_time <= prev.open_time:
            issues.append(
                QualityIssue(
                    code="non_monotonic_timestamp",
                    severity=QualitySeverity.BLOCKING,
                    message=(
                        "open_time not strictly increasing: "
                        f"{prev.open_time.isoformat()} -> {cur.open_time.isoformat()}"
                    ),
                    at=cur.open_time,
                )
            )
    return issues


def _check_continuity(bars: list[Bar], *, timeframe: str, tolerance: float) -> list[QualityIssue]:
    """Flag gaps that are not exactly one timeframe apart (within tolerance)."""
    if len(bars) < 2:
        return []
    dt = timeframe_delta(timeframe)
    max_gap = dt * (1.0 + tolerance)
    issues: list[QualityIssue] = []
    for prev, cur in pairwise(bars):
        gap = cur.open_time - prev.open_time
        if gap > max_gap:
            missing = max(int(gap / dt) - 1, 1)
            issues.append(
                QualityIssue(
                    code="missing_bars",
                    severity=QualitySeverity.BLOCKING,
                    message=(
                        f"gap of {gap} between {prev.open_time.isoformat()} and "
                        f"{cur.open_time.isoformat()} (~{missing} missing bars)"
                    ),
                    at=cur.open_time,
                )
            )
        elif gap < dt and gap != timedelta(0):
            # short gap: treat as misalignment / duplicate-resolution
            issues.append(
                QualityIssue(
                    code="short_gap",
                    severity=QualitySeverity.BLOCKING,
                    message=(
                        f"short gap of {gap} between {prev.open_time.isoformat()} and "
                        f"{cur.open_time.isoformat()} (expected {dt})"
                    ),
                    at=cur.open_time,
                )
            )
    return issues


def _check_spread(bars: list[Bar], *, symbol: str, max_pts: int | None) -> list[QualityIssue]:
    if max_pts is None:
        return []
    return [
        QualityIssue(
            code="abnormal_spread",
            severity=QualitySeverity.WARNING,
            message=(
                f"{symbol} spread {bar.spread_points} pts exceeds ceiling {max_pts} pts "
                f"at {bar.open_time.isoformat()}"
            ),
            at=bar.open_time,
        )
        for bar in bars
        if bar.spread_points > max_pts
    ]


def _check_volume(bars: list[Bar]) -> list[QualityIssue]:
    return [
        QualityIssue(
            code="zero_volume",
            severity=QualitySeverity.WARNING,
            message=f"zero volume at {bar.open_time.isoformat()}",
            at=bar.open_time,
        )
        for bar in bars
        if bar.volume == 0
    ]


def _check_return_outliers(
    bars: list[Bar], *, mad_multiple: float, min_samples: int
) -> list[QualityIssue]:
    """Flag bars whose absolute return exceeds ``k * MAD`` of the series."""
    if len(bars) < min_samples + 1:
        return []
    rets: list[tuple[Bar, float]] = []
    for prev, cur in pairwise(bars):
        if prev.close == 0:
            continue
        rets.append((cur, (cur.close - prev.close) / prev.close))
    if len(rets) < min_samples:
        return []
    abs_rets = [abs(r) for _, r in rets]
    med = median(abs_rets)
    if med <= 0:
        return []
    # Simplified MAD: median of absolute returns (robust, no recentering).
    limit = med * mad_multiple
    issues: list[QualityIssue] = []
    for bar, ret in rets:
        if abs(ret) > limit:
            issues.append(
                QualityIssue(
                    code="return_outlier",
                    severity=QualitySeverity.WARNING,
                    message=(
                        f"return {ret:+.4%} at {bar.open_time.isoformat()} is > "
                        f"{mad_multiple}x median |return| ({med:+.4%})"
                    ),
                    at=bar.open_time,
                )
            )
    return issues


# --- public entrypoint ------------------------------------------------------


def run_quality_gates(
    bars: list[Bar], *, symbol: str, timeframe: str, config: QualityConfig | None = None
) -> QualityReport:
    """Run every gate over ``bars`` and return a :class:`QualityReport`."""
    cfg = config or QualityConfig()
    issues: list[QualityIssue] = []
    if not bars:
        return QualityReport(
            symbol=symbol,
            timeframe=timeframe,
            n_bars=0,
            issues=[
                QualityIssue(
                    code="empty_series",
                    severity=QualitySeverity.BLOCKING,
                    message="no bars supplied for quality check",
                )
            ],
        )

    issues.extend(_check_timestamps(bars))
    issues.extend(_check_continuity(bars, timeframe=timeframe, tolerance=cfg.gap_tolerance))
    issues.extend(_check_spread(bars, symbol=symbol, max_pts=cfg.resolve_spread_max(symbol)))
    issues.extend(_check_volume(bars))
    issues.extend(
        _check_return_outliers(
            bars,
            mad_multiple=cfg.return_outlier_mad_multiple,
            min_samples=cfg.return_outlier_min_samples,
        )
    )
    return QualityReport(
        symbol=symbol,
        timeframe=timeframe,
        n_bars=len(bars),
        issues=issues,
    )
