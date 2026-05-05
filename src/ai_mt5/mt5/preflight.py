"""Issue #3 — Closed Bar preflight + dry_run order_check.

Operator-facing readiness check for a live MT5 demo terminal:

1. Connect through the bridge.
2. Confirm the symbol is selected and tradeable.
3. Pull the latest N closed bars and run them through the same quality
   gates (issue #6) the live ``TickRunner`` uses.
4. Build a synthetic ``order_check`` request (no ``order_send``) and
   confirm the broker accepts it. ``order_check`` is server-side
   validation only — it never opens a position — so it is safe under
   the dry_run charter.

The output is a :class:`PreflightReport` with ``ok: bool`` and a list
of failures suitable for the audit trail and the operator CLI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ..config.models import AppConfig
from ..data.quality import QualityConfig, QualityReport, run_quality_gates
from ..domain.bar import Bar
from .client import (
    ORDER_TYPE_BUY,
    TRADE_ACTION_DEAL,
    MT5Client,
    MT5ConnectionError,
)

# MT5 retcodes we treat as "broker would accept this trade".
RETCODE_DONE = 10009
RETCODE_PLACED = 10008
RETCODE_DONE_PARTIAL = 10010
ACCEPTABLE_RETCODES = frozenset({RETCODE_DONE, RETCODE_PLACED, RETCODE_DONE_PARTIAL})


@dataclass(frozen=True)
class PreflightReport:
    ok: bool
    checked_at: datetime
    symbol: str
    timeframe: str
    bars_received: int
    quality: QualityReport | None
    order_check: dict[str, Any] | None
    failures: tuple[str, ...] = field(default_factory=tuple)
    terminal: dict[str, Any] | None = None
    account: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "checked_at": self.checked_at.isoformat(),
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "bars_received": self.bars_received,
            "quality": (
                None
                if self.quality is None
                else {
                    "ok": self.quality.ok,
                    "blocking_issues": [
                        {"code": i.code, "message": i.message} for i in self.quality.blocking_issues
                    ],
                    "warnings": [
                        {"code": i.code, "message": i.message} for i in self.quality.warnings
                    ],
                }
            ),
            "order_check": self.order_check,
            "failures": list(self.failures),
            "terminal": self.terminal,
            "account": self.account,
        }


def _bars_from_rates(symbol: str, timeframe: str, rates: list[dict[str, Any]]) -> list[Bar]:
    bars: list[Bar] = []
    for row in rates:
        bars.append(
            Bar(
                symbol=symbol,
                timeframe=timeframe,
                open_time=row["open_time"],
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                volume=row["volume"],
                spread_points=row["spread_points"],
                is_closed=True,
            )
        )
    return bars


def run_preflight(
    *,
    client: MT5Client,
    config: AppConfig,
    now: datetime,
    bar_count: int = 200,
    test_volume: float = 0.01,
) -> PreflightReport:
    """Run the live readiness check and return a report.

    Caller is responsible for supplying a connected (or mock)
    :class:`MT5Client`. ``test_volume`` is passed to ``order_check`` only
    — never to ``order_send`` — so this function cannot place trades.
    """
    failures: list[str] = []
    symbol_cfg = config.primary_symbol()
    symbol = symbol_cfg.symbol
    timeframe = symbol_cfg.timeframe

    terminal_info: dict[str, Any] | None = None
    account_info: dict[str, Any] | None = None
    quality: QualityReport | None = None
    order_check: dict[str, Any] | None = None
    bars: list[Bar] = []

    try:
        terminal = client.terminal_info()
        terminal_info = {
            "connected": bool(getattr(terminal, "connected", False)),
            "trade_allowed": bool(getattr(terminal, "trade_allowed", False)),
            "name": str(getattr(terminal, "name", "")),
        }
        if not terminal_info["connected"]:
            failures.append("terminal_disconnected")
        if not terminal_info["trade_allowed"]:
            failures.append("trade_not_allowed")

        account = client.account_info()
        account_info = {
            "login": int(getattr(account, "login", 0)),
            "server": str(getattr(account, "server", "")),
            "currency": str(getattr(account, "currency", "")),
            "balance": float(getattr(account, "balance", 0.0)),
            "equity": float(getattr(account, "equity", 0.0)),
            "trade_allowed": bool(getattr(account, "trade_allowed", False)),
        }
        if not account_info["trade_allowed"]:
            failures.append("account_trade_disabled")

        sym_info = client.symbol_info(symbol)
        if not getattr(sym_info, "visible", True):
            failures.append(f"symbol_not_visible:{symbol}")
        trade_mode = int(getattr(sym_info, "trade_mode", 0))
        # 0=disabled per MT5 convention; >0 means tradeable in some mode.
        if trade_mode == 0:
            failures.append(f"symbol_trade_disabled:{symbol}")

        rates = client.copy_rates_from_pos(
            symbol=symbol,
            timeframe=timeframe,
            start_pos=1,  # skip the running bar
            count=bar_count,
        )
        bars = _bars_from_rates(symbol=symbol, timeframe=timeframe, rates=rates)

        quality_cfg = QualityConfig(
            return_outlier_mad_multiple=config.data_quality.return_outlier_mad_multiple,
            return_outlier_min_samples=config.data_quality.return_outlier_min_samples,
            gap_tolerance=config.data_quality.gap_tolerance,
            spread_max_points=dict(config.data_quality.spread_max_points),
        )
        quality = run_quality_gates(
            bars,
            symbol=symbol,
            timeframe=timeframe,
            config=quality_cfg,
        )
        if not quality.ok:
            failures.extend(f"quality:{i.code}" for i in quality.blocking_issues)

        # order_check synthesises a market order; broker validates only.
        tick = client.symbol_info_tick(symbol)
        ask = float(getattr(tick, "ask", 0.0))
        if ask <= 0:
            failures.append("symbol_no_ask_price")
        else:
            order_check = client.order_check(
                {
                    "action": TRADE_ACTION_DEAL,
                    "symbol": symbol,
                    "volume": test_volume,
                    "type": ORDER_TYPE_BUY,
                    "price": ask,
                    "deviation": config.execution.deviation_points,
                    "magic": config.execution.magic,
                    # MT5 caps the broker comment at 31 characters; the
                    # config field allows up to 31 already, so suffixing
                    # "-preflight" can overflow and trigger spurious
                    # broker rejections. Truncate to be safe.
                    "comment": f"{config.execution.order_comment}-preflight"[:31],
                    "type_time": "ORDER_TIME_GTC",
                    "type_filling": "ORDER_FILLING_IOC",
                }
            )
            if order_check["retcode"] not in ACCEPTABLE_RETCODES:
                failures.append(
                    f"order_check_rejected:retcode={order_check['retcode']}:"
                    f"{order_check['comment']}"
                )

    except MT5ConnectionError as exc:
        failures.append(f"bridge_error:{exc}")
    except (EOFError, ConnectionError, OSError, TimeoutError) as exc:
        # RPyC transport errors when the bridge drops mid-call do NOT
        # subclass MT5ConnectionError. Same pattern as MT5BridgeStatus
        # (status.py) — surface them as a structured failure so the
        # operator gets JSON instead of a raw traceback.
        failures.append(f"bridge_transport_error:{type(exc).__name__}:{exc}")

    return PreflightReport(
        ok=not failures,
        checked_at=now,
        symbol=symbol,
        timeframe=timeframe,
        bars_received=len(bars),
        quality=quality,
        order_check=order_check,
        failures=tuple(failures),
        terminal=terminal_info,
        account=account_info,
    )
