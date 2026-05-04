"""Walk-forward window splitting.

Each :class:`WalkForwardWindow` carves an ordered bar series into three
non-overlapping ranges -- ``train``, ``validation``, ``oos`` -- expressed
as half-open ``[start, end)`` index pairs. The contract is intentionally
strict:

* ``train.end == validation.start`` and ``validation.end == oos.start``,
  so consecutive ranges touch but never overlap.
* Windows are emitted in ascending start order; consecutive windows share
  no OOS bars (rolling step is at least the OOS size).

Splitting is purely arithmetic (indices only) so it can be reused across
CSV fixtures, in-memory bar lists, or :class:`BarStore` outputs without
loading a single bar.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass


@dataclass(frozen=True)
class IndexRange:
    """Half-open range ``[start, end)`` over bar indices."""

    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start < 0:
            raise ValueError("start must be >= 0")
        if self.end < self.start:
            raise ValueError("end must be >= start")

    def __len__(self) -> int:
        return self.end - self.start

    @property
    def is_empty(self) -> bool:
        return self.end == self.start


@dataclass(frozen=True)
class WalkForwardWindow:
    """One ``train | validation | oos`` slice for a single backtest fold."""

    train: IndexRange
    validation: IndexRange
    oos: IndexRange

    def __post_init__(self) -> None:
        if self.train.end != self.validation.start:
            raise ValueError("train.end must equal validation.start (no overlap, no gap)")
        if self.validation.end != self.oos.start:
            raise ValueError("validation.end must equal oos.start (no overlap, no gap)")
        if self.train.is_empty:
            raise ValueError("train range must be non-empty")
        if self.oos.is_empty:
            raise ValueError("oos range must be non-empty")

    @property
    def history_end(self) -> int:
        """Last index *not* part of OOS -- safe upper bound for warm-up."""
        return self.validation.end


def walk_forward_windows(
    n_bars: int,
    *,
    train: int,
    validation: int,
    oos: int,
    step: int | None = None,
) -> Iterator[WalkForwardWindow]:
    """Yield rolling :class:`WalkForwardWindow` instances over ``n_bars``.

    Args:
        n_bars: Total number of bars available.
        train: Number of bars in each train range.
        validation: Number of bars in each validation range.
        oos: Number of bars in each OOS range.
        step: How many bars to advance ``train.start`` between windows.
            Defaults to ``oos`` (no overlap of OOS ranges).

    Raises:
        ValueError: If any of the sizes are non-positive, ``step`` is
            non-positive, or fewer than one window can fit in ``n_bars``.
    """
    if train <= 0:
        raise ValueError("train must be positive")
    if validation <= 0:
        raise ValueError("validation must be positive")
    if oos <= 0:
        raise ValueError("oos must be positive")
    advance = step if step is not None else oos
    if advance <= 0:
        raise ValueError("step must be positive")

    fold = train + validation + oos
    if n_bars < fold:
        raise ValueError(f"need at least {fold} bars, got {n_bars}")

    start = 0
    while start + fold <= n_bars:
        train_range = IndexRange(start=start, end=start + train)
        val_range = IndexRange(start=train_range.end, end=train_range.end + validation)
        oos_range = IndexRange(start=val_range.end, end=val_range.end + oos)
        yield WalkForwardWindow(train=train_range, validation=val_range, oos=oos_range)
        start += advance
