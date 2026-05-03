"""Issue #7: offline evaluation reports."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ai_mt5.domain.bar import Bar
from ai_mt5.models import TimesFMAdapter, evaluate_adapter
from ai_mt5.models.evaluation import EvaluationReport


def _trending_bars(n: int) -> list[Bar]:
    base = datetime(2024, 1, 1, tzinfo=UTC)
    dt = timedelta(minutes=15)
    price = 1.1000
    out: list[Bar] = []
    for i in range(n):
        price *= 1.0002
        out.append(
            Bar(
                symbol="EURUSD",
                timeframe="M15",
                open_time=base + i * dt,
                open=price,
                high=price * 1.0001,
                low=price * 0.9999,
                close=price,
                volume=10.0,
                spread_points=5,
            )
        )
    return out


def test_evaluation_report_for_trend_returns_metrics() -> None:
    bars = _trending_bars(60)
    report = evaluate_adapter(TimesFMAdapter(), bars)
    assert isinstance(report, EvaluationReport)
    assert report.adapter_name == "timesfm"
    assert report.adapter_version == "mock-0.1.0"
    assert report.n_decisions > 0
    assert 0.0 <= report.direction_accuracy <= 1.0


def test_evaluation_report_respects_min_history() -> None:
    bars = _trending_bars(10)
    report = evaluate_adapter(TimesFMAdapter(), bars, min_history=21)
    assert not report.ok
    assert "insufficient_history" in report.limitations


def test_evaluation_applies_cost() -> None:
    bars = _trending_bars(60)
    report = evaluate_adapter(TimesFMAdapter(), bars, cost_per_trade=0.01)
    # Cost should subtract from edge.
    no_cost = evaluate_adapter(TimesFMAdapter(), bars, cost_per_trade=0.0)
    assert report.edge_after_cost <= no_cost.edge_after_cost
