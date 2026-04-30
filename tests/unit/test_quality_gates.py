"""Issue #6: individual market-data quality gates."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ai_mt5.data.quality import QualityConfig, QualitySeverity, run_quality_gates
from ai_mt5.domain.bar import Bar


def _bar(
    *,
    open_time: datetime,
    close: float = 1.1000,
    volume: float = 10.0,
    spread_points: int = 5,
) -> Bar:
    return Bar(
        symbol="EURUSD",
        timeframe="M15",
        open_time=open_time,
        open=1.1000,
        high=max(1.1010, close),
        low=min(1.0990, close),
        close=close,
        volume=volume,
        spread_points=spread_points,
    )


def _series(n: int) -> list[Bar]:
    base = datetime(2024, 1, 1, tzinfo=UTC)
    dt = timedelta(minutes=15)
    return [_bar(open_time=base + i * dt) for i in range(n)]


def test_empty_series_is_blocking() -> None:
    report = run_quality_gates([], symbol="EURUSD", timeframe="M15")
    assert not report.ok
    assert any(i.code == "empty_series" for i in report.blocking_issues)


def test_clean_series_passes() -> None:
    report = run_quality_gates(_series(10), symbol="EURUSD", timeframe="M15")
    assert report.ok
    assert report.warnings == []


def test_missing_bar_is_blocking() -> None:
    bars = _series(10)
    gapped = bars[:4] + bars[6:]  # drop two bars
    report = run_quality_gates(gapped, symbol="EURUSD", timeframe="M15")
    assert not report.ok
    assert any(i.code == "missing_bars" for i in report.blocking_issues)


def test_short_gap_is_blocking() -> None:
    base = datetime(2024, 1, 1, tzinfo=UTC)
    bars = [
        _bar(open_time=base),
        _bar(open_time=base + timedelta(minutes=7)),  # not a full M15 bar apart
    ]
    report = run_quality_gates(bars, symbol="EURUSD", timeframe="M15")
    assert not report.ok
    assert any(i.code == "short_gap" for i in report.blocking_issues)


def test_non_monotonic_timestamps_is_blocking() -> None:
    base = datetime(2024, 1, 1, tzinfo=UTC)
    dt = timedelta(minutes=15)
    bars = [
        _bar(open_time=base),
        _bar(open_time=base + dt),
        _bar(open_time=base + dt),  # duplicate
    ]
    report = run_quality_gates(bars, symbol="EURUSD", timeframe="M15")
    assert not report.ok
    assert any(i.code == "non_monotonic_timestamp" for i in report.blocking_issues)


def test_zero_volume_is_warning_not_blocking() -> None:
    bars = _series(10)
    bars[3] = _bar(open_time=bars[3].open_time, volume=0.0)
    report = run_quality_gates(bars, symbol="EURUSD", timeframe="M15")
    assert report.ok
    assert any(
        w.code == "zero_volume" and w.severity is QualitySeverity.WARNING for w in report.warnings
    )


def test_abnormal_spread_requires_configured_ceiling() -> None:
    bars = _series(5)
    bars[2] = _bar(open_time=bars[2].open_time, spread_points=9999)
    # No ceiling configured -> no issue reported.
    report = run_quality_gates(bars, symbol="EURUSD", timeframe="M15")
    assert report.ok
    assert not any(w.code == "abnormal_spread" for w in report.warnings)
    # Configured ceiling -> warning.
    cfg = QualityConfig(spread_max_points={"EURUSD": 50})
    report = run_quality_gates(bars, symbol="EURUSD", timeframe="M15", config=cfg)
    assert report.ok
    assert any(w.code == "abnormal_spread" for w in report.warnings)


def test_return_outlier_flagged_above_mad_multiple() -> None:
    # 40 bars: tight returns, then one huge jump at index 25.
    base = datetime(2024, 1, 1, tzinfo=UTC)
    dt = timedelta(minutes=15)
    bars: list[Bar] = []
    price = 1.1000
    for i in range(40):
        price *= 1.0001 if i % 2 == 0 else 0.9999
        if i == 25:
            price *= 1.2  # +20% jump
        bars.append(_bar(open_time=base + i * dt, close=price))
    report = run_quality_gates(bars, symbol="EURUSD", timeframe="M15")
    assert report.ok  # outlier is a warning
    assert any(w.code == "return_outlier" for w in report.warnings)


def test_return_outlier_skipped_below_min_samples() -> None:
    cfg = QualityConfig(return_outlier_min_samples=100)
    bars = _series(20)
    report = run_quality_gates(bars, symbol="EURUSD", timeframe="M15", config=cfg)
    assert report.ok
    assert not any(w.code == "return_outlier" for w in report.warnings)
