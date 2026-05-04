"""Walk-forward window splitting must be deterministic and non-overlapping."""

from __future__ import annotations

from itertools import pairwise

import pytest

from ai_mt5.backtest import IndexRange, WalkForwardWindow, walk_forward_windows


def test_index_range_rejects_negative_start() -> None:
    with pytest.raises(ValueError):
        IndexRange(start=-1, end=0)


def test_index_range_rejects_inverted_bounds() -> None:
    with pytest.raises(ValueError):
        IndexRange(start=10, end=5)


def test_walk_forward_window_rejects_overlap() -> None:
    with pytest.raises(ValueError, match=r"train\.end must equal validation\.start"):
        WalkForwardWindow(
            train=IndexRange(0, 10),
            validation=IndexRange(8, 14),
            oos=IndexRange(14, 18),
        )


def test_walk_forward_window_rejects_gap() -> None:
    with pytest.raises(ValueError, match=r"validation\.end must equal oos\.start"):
        WalkForwardWindow(
            train=IndexRange(0, 10),
            validation=IndexRange(10, 14),
            oos=IndexRange(15, 18),
        )


def test_walk_forward_windows_basic_layout() -> None:
    windows = list(walk_forward_windows(n_bars=300, train=100, validation=50, oos=50))
    # 300 - (100+50+50) = 100 bars of slack, step=oos=50 -> windows at start 0, 50, 100
    starts = [w.train.start for w in windows]
    assert starts == [0, 50, 100]
    for w in windows:
        assert len(w.train) == 100
        assert len(w.validation) == 50
        assert len(w.oos) == 50
        # ranges are contiguous
        assert w.train.end == w.validation.start
        assert w.validation.end == w.oos.start


def test_walk_forward_windows_no_overlap_default_step() -> None:
    windows = list(walk_forward_windows(n_bars=400, train=100, validation=50, oos=50))
    oos_ranges = [(w.oos.start, w.oos.end) for w in windows]
    # consecutive OOS ranges must not overlap when step defaults to oos
    for (_, prev_end), (next_start, _) in pairwise(oos_ranges):
        assert next_start >= prev_end


def test_walk_forward_windows_custom_step_allows_overlap() -> None:
    # step < oos means OOS ranges overlap; allowed by spec
    windows = list(walk_forward_windows(n_bars=300, train=100, validation=50, oos=50, step=25))
    assert len(windows) > 4


def test_walk_forward_windows_rejects_too_few_bars() -> None:
    with pytest.raises(ValueError, match="need at least"):
        list(walk_forward_windows(n_bars=100, train=100, validation=50, oos=50))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"train": 0},
        {"validation": 0},
        {"oos": 0},
        {"step": 0},
    ],
)
def test_walk_forward_windows_rejects_non_positive_sizes(kwargs: dict[str, int]) -> None:
    base: dict[str, int] = {"train": 50, "validation": 25, "oos": 25, "step": 25}
    base.update(kwargs)
    with pytest.raises(ValueError):
        list(walk_forward_windows(n_bars=300, **base))


def test_window_history_end_excludes_oos() -> None:
    windows = list(walk_forward_windows(n_bars=200, train=100, validation=50, oos=50))
    w = windows[0]
    assert w.history_end == w.oos.start
    assert w.history_end < w.oos.end
