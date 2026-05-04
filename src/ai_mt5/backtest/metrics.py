"""Out-of-sample backtest metrics.

The metrics here intentionally mirror the acceptance criteria for issue #10:
out-of-sample PnL, drawdown, Sharpe, Calmar, profit factor, trade count, and
win rate. All inputs are deposit-currency PnL series; no broker assumptions
beyond what the cost model already encoded.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import fmean, pstdev


@dataclass(frozen=True)
class BacktestMetrics:
    """Standard OOS metrics for a single backtest run.

    Attributes:
        n_trades: Number of closed trades.
        n_wins / n_losses: Trades whose net (post-cost) PnL is strictly
            positive / strictly negative. Break-even trades are neither.
        win_rate: ``n_wins / n_trades`` (0.0 when no trades).
        gross_pnl: Sum of net trade PnLs (deposit currency).
        profit_factor: ``sum(wins) / |sum(losses)|`` (``inf`` if no losers,
            ``0.0`` if no trades).
        max_drawdown: Maximum peak-to-trough drop on the cumulative equity
            curve, expressed in deposit currency. Always >= 0.
        max_drawdown_pct: ``max_drawdown / max(running_peak)``, in [0, 1].
        sharpe: Annualised Sharpe ratio over per-trade returns (zero
            risk-free assumption). ``0.0`` when stdev is 0 or trade count <2.
        calmar: ``annualised_return / max_drawdown_pct`` (0.0 if no DD);
            ``annualised_return = raw_return * bars_per_year /
            (n_trades * bars_per_trade)`` so windows of different length
            stay comparable.
        avg_trade: Mean per-trade net PnL.
        bars_per_year: Annualisation factor used for Sharpe/Calmar.
    """

    n_trades: int
    n_wins: int
    n_losses: int
    win_rate: float
    gross_pnl: float
    profit_factor: float
    max_drawdown: float
    max_drawdown_pct: float
    sharpe: float
    calmar: float
    avg_trade: float
    bars_per_year: float


def equity_curve(initial_equity: float, trade_pnls: list[float]) -> list[float]:
    """Running equity after each trade, starting from ``initial_equity``."""
    if initial_equity <= 0:
        raise ValueError("initial_equity must be positive")
    out: list[float] = [initial_equity]
    cum = initial_equity
    for p in trade_pnls:
        cum += p
        out.append(cum)
    return out


def max_drawdown(curve: list[float]) -> tuple[float, float]:
    """Return ``(absolute, fraction)`` worst peak-to-trough drop.

    Both values are non-negative. Fraction is normalised by the running
    *peak*, which matches the standard "max DD as a percentage of equity"
    definition and avoids division by the (smaller) trough.
    """
    if not curve:
        return 0.0, 0.0
    peak = curve[0]
    worst_abs = 0.0
    worst_frac = 0.0
    for v in curve:
        if v > peak:
            peak = v
        drop = peak - v
        if drop > worst_abs:
            worst_abs = drop
        if peak > 0 and drop / peak > worst_frac:
            worst_frac = drop / peak
    return worst_abs, worst_frac


def compute_metrics(
    trade_pnls: list[float],
    *,
    initial_equity: float,
    bars_per_year: float,
    bars_per_trade: float = 1.0,
) -> BacktestMetrics:
    """Aggregate ``trade_pnls`` (post-cost) into a :class:`BacktestMetrics`.

    ``bars_per_year`` is ``bars_per_session * trading_sessions_per_year``;
    e.g. 96 M15 bars per 24h session * 252 sessions ~= 24_192. The caller
    knows the bar timeframe so we accept the constant directly. ``bars_per_trade``
    is the *average* hold length used to scale Sharpe from per-trade to
    per-bar variance and back to annualised; defaults to 1 (per-trade Sharpe).
    """
    if initial_equity <= 0:
        raise ValueError("initial_equity must be positive")
    if bars_per_year <= 0:
        raise ValueError("bars_per_year must be positive")
    if bars_per_trade <= 0:
        raise ValueError("bars_per_trade must be positive")

    n = len(trade_pnls)
    wins = [p for p in trade_pnls if p > 0]
    losses = [p for p in trade_pnls if p < 0]

    gross = sum(trade_pnls)
    if not wins and not losses:
        profit_factor = 0.0
    elif not losses:
        profit_factor = float("inf")
    else:
        profit_factor = sum(wins) / abs(sum(losses))

    curve = equity_curve(initial_equity, trade_pnls)
    dd_abs, dd_frac = max_drawdown(curve)

    if n >= 2:
        # Per-trade returns relative to entry equity (good enough offline).
        rets = [p / initial_equity for p in trade_pnls]
        mu = fmean(rets)
        sigma = pstdev(rets)
        if sigma > 0:
            trades_per_year = bars_per_year / max(bars_per_trade, 1.0)
            sharpe = (mu / sigma) * math.sqrt(trades_per_year)
        else:
            sharpe = 0.0
    else:
        sharpe = 0.0

    # Calmar uses *years*: annualise the raw return so windows of different
    # length are comparable. ``total_bars`` is the wall-clock span the
    # window covered (n_trades * bars_per_trade); for empty windows we
    # short-circuit to 0.
    raw_return = gross / initial_equity
    total_bars = n * bars_per_trade
    if total_bars > 0:
        annualisation = bars_per_year / total_bars
        annualised_return = raw_return * annualisation
    else:
        annualised_return = raw_return
    calmar = annualised_return / dd_frac if dd_frac > 0 else 0.0

    return BacktestMetrics(
        n_trades=n,
        n_wins=len(wins),
        n_losses=len(losses),
        win_rate=(len(wins) / n) if n else 0.0,
        gross_pnl=gross,
        profit_factor=profit_factor,
        max_drawdown=dd_abs,
        max_drawdown_pct=dd_frac,
        sharpe=sharpe,
        calmar=calmar,
        avg_trade=fmean(trade_pnls) if n else 0.0,
        bars_per_year=bars_per_year,
    )
