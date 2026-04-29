"""Risk Decision gate.

The manager composes :mod:`position_sizing`, :mod:`stops`, and the kill switch
into a single deterministic ``evaluate`` call. Every check that fails appends
a *machine-readable reason* to the ``rejected_by`` list -- nothing short-
circuits, so an audit reader can see *all* applicable reasons in one place.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Literal

from ..config.models import RiskConfig
from ..domain.forecast import MetaSignal
from ..domain.market import AccountSnapshot, MarketSnapshot, NewsEvent
from ..domain.risk import RiskDecision
from .kill_switch import KillSwitch
from .position_sizing import size_position
from .stops import compute_sl_tp

Side = Literal["BUY", "SELL"]


class RiskManager:
    """Deterministic Risk Decision gate."""

    def __init__(
        self,
        config: RiskConfig,
        kill_switch: KillSwitch,
        *,
        magic: int,
        order_comment: str,
    ) -> None:
        self._cfg = config
        self._kill = kill_switch
        self._magic = magic
        self._comment = order_comment

    # -- public --------------------------------------------------------------

    def evaluate(
        self,
        signal: MetaSignal,
        account: AccountSnapshot,
        market: MarketSnapshot,
        *,
        news: Sequence[NewsEvent] = (),
        now: datetime | None = None,
    ) -> RiskDecision:
        rejected: list[str] = []

        if self._kill.is_engaged():
            rejected.append("kill_switch_engaged")

        rejected.extend(self._check_signal(signal))
        rejected.extend(self._check_account(account))
        rejected.extend(self._check_spread(market))
        rejected.extend(self._check_news(news=news, market=market, now=now))

        if signal.direction == "HOLD":
            rejected.append("signal_hold")

        # If we already have hard rejections, do not bother sizing.
        if rejected:
            return RiskDecision.reject(rejected, magic=self._magic, comment=self._comment)

        side: Side = signal.direction  # type: ignore[assignment]
        entry_price = market.ask if side == "BUY" else market.bid

        stops = compute_sl_tp(
            side=side,
            entry_price=entry_price,
            atr=market.atr,
            sl_atr_min=self._cfg.sl_atr_min,
            sl_atr_max=self._cfg.sl_atr_max,
            tp_atr=self._cfg.tp_atr,
            rr_min=self._cfg.rr_min,
            stop_level_points=market.stop_level_points,
            point_size=market.point_size,
        )
        if not stops.approved:
            return RiskDecision.reject(stops.rejected_by, magic=self._magic, comment=self._comment)

        sizing = size_position(
            equity=account.equity,
            base_risk_pct=self._cfg.base_risk_per_trade,
            min_risk_pct=self._cfg.min_risk_per_trade,
            max_risk_pct=self._cfg.max_risk_per_trade,
            sl_distance_price=stops.sl_distance_price,
            contract_size=market.contract_size,
            volume_min=market.volume_min,
            volume_max=market.volume_max,
            volume_step=market.volume_step,
        )
        if not sizing.approved:
            return RiskDecision.reject(sizing.rejected_by, magic=self._magic, comment=self._comment)

        margin_required = sizing.volume * market.margin_per_lot
        if margin_required > account.free_margin * self._cfg.margin_safety:
            return RiskDecision.reject(
                ["insufficient_margin"],
                magic=self._magic,
                comment=self._comment,
            )

        return RiskDecision(
            approved=True,
            side=side,
            volume=sizing.volume,
            sl=stops.sl,
            tp=stops.tp,
            magic=self._magic,
            comment=self._comment,
            reason=(
                f"signal={side} score={signal.final_score:.4f} "
                f"agreement={signal.agreement:.2f} risk={sizing.risk_amount:.2f}"
            ),
            rejected_by=[],
        )

    # -- internal checks -----------------------------------------------------

    def _check_signal(self, signal: MetaSignal) -> list[str]:
        out: list[str] = []
        if signal.veto_reasons:
            out.append("signal_vetoed")
        if signal.direction not in ("BUY", "SELL", "HOLD"):
            out.append("invalid_signal_direction")
        return out

    def _check_account(self, account: AccountSnapshot) -> list[str]:
        out: list[str] = []
        if account.equity <= 0:
            out.append("non_positive_equity")
        if account.daily_pnl_pct <= -self._cfg.max_daily_loss:
            out.append("max_daily_loss_breached")
        if account.drawdown_pct >= self._cfg.max_total_drawdown:
            out.append("max_drawdown_breached")
        if account.open_positions >= self._cfg.max_total_positions:
            out.append("max_total_positions_reached")
        if account.open_positions_for_symbol >= self._cfg.max_positions_per_symbol:
            out.append("max_positions_for_symbol_reached")
        if account.trades_today >= self._cfg.max_trades_per_day:
            out.append("max_trades_per_day_reached")
        if account.consecutive_losses >= self._cfg.max_consecutive_losses:
            out.append("max_consecutive_losses_reached")
        return out

    def _check_spread(self, market: MarketSnapshot) -> list[str]:
        max_pts = self._cfg.spread_max_points.get(market.symbol)
        if max_pts is not None and market.spread_points > max_pts:
            return ["spread_too_wide"]
        return []

    def _check_news(
        self,
        *,
        news: Sequence[NewsEvent],
        market: MarketSnapshot,
        now: datetime | None,
    ) -> list[str]:
        if not news:
            return []
        ref = now or market.timestamp
        for event in news:
            if event.symbol != market.symbol:
                continue
            window = self._cfg.news_window_minutes.get(event.impact)
            if not window or len(window) != 2:
                continue
            before, after = window
            start = event.scheduled_at + timedelta(minutes=before)
            end = event.scheduled_at + timedelta(minutes=after)
            if start <= ref <= end:
                return [f"news_window_{event.impact}"]
        return []
