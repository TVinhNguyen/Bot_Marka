"""Issue #4: Risk Decision gate tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from ai_mt5.domain.forecast import MetaSignal
from ai_mt5.domain.market import NewsEvent
from ai_mt5.risk import RiskManager
from ai_mt5.risk.kill_switch import InMemoryKillSwitch


def _signal(direction: str = "BUY", *, vetoed: bool = False) -> MetaSignal:
    return MetaSignal(
        direction=direction,  # type: ignore[arg-type]
        final_score=0.5 if direction == "BUY" else -0.5 if direction == "SELL" else 0.0,
        raw_score=0.5,
        agreement=0.9,
        confidence=0.7,
        veto_reasons=["veto_x"] if vetoed else [],
        components={},
    )


def _make_manager(app_config, kill: InMemoryKillSwitch | None = None) -> RiskManager:
    return RiskManager(
        app_config.risk,
        kill or InMemoryKillSwitch(),
        magic=app_config.execution.magic,
        order_comment=app_config.execution.order_comment,
    )


def test_approves_buy_signal_with_sl_tp_and_volume(
    app_config, account_snapshot, market_snapshot
) -> None:
    mgr = _make_manager(app_config)
    decision = mgr.evaluate(_signal("BUY"), account_snapshot, market_snapshot)

    assert decision.approved
    assert decision.side == "BUY"
    assert decision.volume > 0
    assert decision.sl is not None and decision.sl < market_snapshot.ask
    assert decision.tp is not None and decision.tp > market_snapshot.ask
    assert decision.magic == app_config.execution.magic
    assert decision.comment == app_config.execution.order_comment
    assert not decision.rejected_by


def test_approves_sell_signal_with_correct_stops(
    app_config, account_snapshot, market_snapshot
) -> None:
    mgr = _make_manager(app_config)
    decision = mgr.evaluate(_signal("SELL"), account_snapshot, market_snapshot)
    assert decision.approved
    assert decision.side == "SELL"
    assert decision.sl > market_snapshot.bid
    assert decision.tp < market_snapshot.bid


def test_hold_signal_is_rejected(app_config, account_snapshot, market_snapshot) -> None:
    mgr = _make_manager(app_config)
    decision = mgr.evaluate(_signal("HOLD"), account_snapshot, market_snapshot)
    assert not decision.approved
    assert "signal_hold" in decision.rejected_by


def test_kill_switch_forces_reject(app_config, account_snapshot, market_snapshot) -> None:
    kill = InMemoryKillSwitch(engaged=True)
    mgr = _make_manager(app_config, kill=kill)
    decision = mgr.evaluate(_signal("BUY"), account_snapshot, market_snapshot)
    assert not decision.approved
    assert "kill_switch_engaged" in decision.rejected_by


def test_clearing_kill_switch_unblocks(app_config, account_snapshot, market_snapshot) -> None:
    kill = InMemoryKillSwitch(engaged=True)
    mgr = _make_manager(app_config, kill=kill)
    assert not mgr.evaluate(_signal("BUY"), account_snapshot, market_snapshot).approved
    kill.clear()
    assert mgr.evaluate(_signal("BUY"), account_snapshot, market_snapshot).approved


def test_news_window_blocks_trade(app_config, account_snapshot, market_snapshot) -> None:
    mgr = _make_manager(app_config)
    event = NewsEvent(
        symbol="EURUSD",
        impact="high",
        scheduled_at=market_snapshot.timestamp + timedelta(minutes=10),
    )
    decision = mgr.evaluate(_signal("BUY"), account_snapshot, market_snapshot, news=[event])
    assert not decision.approved
    assert "news_window_high" in decision.rejected_by


def test_news_window_outside_does_not_block(app_config, account_snapshot, market_snapshot) -> None:
    mgr = _make_manager(app_config)
    event = NewsEvent(
        symbol="EURUSD",
        impact="high",
        scheduled_at=market_snapshot.timestamp - timedelta(hours=2),
    )
    decision = mgr.evaluate(_signal("BUY"), account_snapshot, market_snapshot, news=[event])
    assert decision.approved


def test_spread_too_wide_rejects(app_config, account_snapshot, market_snapshot) -> None:
    mgr = _make_manager(app_config)
    wide = replace(market_snapshot, spread_points=999)
    decision = mgr.evaluate(_signal("BUY"), account_snapshot, wide)
    assert not decision.approved
    assert "spread_too_wide" in decision.rejected_by


def test_daily_loss_breach_rejects(app_config, account_snapshot, market_snapshot) -> None:
    mgr = _make_manager(app_config)
    bad_account = replace(account_snapshot, daily_pnl_pct=-0.05)
    decision = mgr.evaluate(_signal("BUY"), bad_account, market_snapshot)
    assert not decision.approved
    assert "max_daily_loss_breached" in decision.rejected_by


def test_drawdown_breach_rejects(app_config, account_snapshot, market_snapshot) -> None:
    mgr = _make_manager(app_config)
    bad_account = replace(account_snapshot, drawdown_pct=0.10)
    decision = mgr.evaluate(_signal("BUY"), bad_account, market_snapshot)
    assert not decision.approved
    assert "max_drawdown_breached" in decision.rejected_by


def test_max_positions_for_symbol_rejects(app_config, account_snapshot, market_snapshot) -> None:
    mgr = _make_manager(app_config)
    bad_account = replace(account_snapshot, open_positions=1, open_positions_for_symbol=1)
    decision = mgr.evaluate(_signal("BUY"), bad_account, market_snapshot)
    assert not decision.approved
    assert "max_positions_for_symbol_reached" in decision.rejected_by


def test_max_consecutive_losses_rejects(app_config, account_snapshot, market_snapshot) -> None:
    mgr = _make_manager(app_config)
    bad_account = replace(account_snapshot, consecutive_losses=3)
    decision = mgr.evaluate(_signal("BUY"), bad_account, market_snapshot)
    assert not decision.approved
    assert "max_consecutive_losses_reached" in decision.rejected_by


def test_insufficient_margin_rejects(app_config, account_snapshot, market_snapshot) -> None:
    mgr = _make_manager(app_config)
    poor = replace(account_snapshot, free_margin=10.0)
    decision = mgr.evaluate(_signal("BUY"), poor, market_snapshot)
    assert not decision.approved
    assert "insufficient_margin" in decision.rejected_by


def test_signal_veto_rejects(app_config, account_snapshot, market_snapshot) -> None:
    mgr = _make_manager(app_config)
    decision = mgr.evaluate(_signal("BUY", vetoed=True), account_snapshot, market_snapshot)
    assert not decision.approved
    assert "signal_vetoed" in decision.rejected_by


def test_all_applicable_reasons_collected(app_config, account_snapshot, market_snapshot) -> None:
    """Multiple violations must all show up in rejected_by, not just the first."""
    mgr = _make_manager(app_config, kill=InMemoryKillSwitch(engaged=True))
    bad_account = replace(
        account_snapshot,
        daily_pnl_pct=-0.05,
        drawdown_pct=0.10,
        consecutive_losses=10,
        trades_today=999,
    )
    wide = replace(market_snapshot, spread_points=999)
    decision = mgr.evaluate(_signal("HOLD"), bad_account, wide)
    assert not decision.approved
    expected = {
        "kill_switch_engaged",
        "max_daily_loss_breached",
        "max_drawdown_breached",
        "max_consecutive_losses_reached",
        "max_trades_per_day_reached",
        "spread_too_wide",
        "signal_hold",
    }
    assert expected.issubset(set(decision.rejected_by))
