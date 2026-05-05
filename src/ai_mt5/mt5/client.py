"""RPyC client for the ``mt5linux`` bridge.

Connects to a Windows host running ``python -m mt5linux <python.exe>`` and
exposes a small, typed surface against the remote ``MetaTrader5`` module.

The bridge dependency (``rpyc``) is installed via the ``mt5`` optional
dependency group; the ``MetaTrader5`` package itself is **never**
imported on this Linux side — it is only used remotely on the bridge.

This module deliberately keeps the surface narrow: every method we need
on the bot side is a thin pass-through to the remote ``MetaTrader5``
module. That keeps the unit-testing surface mockable (any object with
the same method signatures plugs into :class:`MT5Client`) without ever
needing a live broker.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from ..utils.logging_setup import get_logger

_log = get_logger("ai_mt5.mt5.client")


class MT5ConnectionError(RuntimeError):
    """Raised when the bridge or remote terminal cannot satisfy a request."""


@dataclass(frozen=True)
class MT5BridgeConfig:
    """Connection parameters for the ``mt5linux`` RPyC bridge.

    All fields are typically populated from environment variables /
    Devin secrets (`MT5_BRIDGE_HOST`, `MT5_BRIDGE_PORT`,
    `MT5_DEMO_LOGIN`, `MT5_DEMO_PASSWORD`, `MT5_DEMO_SERVER`).
    """

    host: str
    port: int = 18812
    login: int | None = None
    password: str | None = None
    server: str | None = None
    timeout_ms: int = 60_000

    @classmethod
    def from_env(cls, *, prefix: str = "MT5") -> MT5BridgeConfig:
        host = os.environ.get(f"{prefix}_BRIDGE_HOST")
        if not host:
            raise MT5ConnectionError(f"{prefix}_BRIDGE_HOST is not set in environment")
        port_raw = os.environ.get(f"{prefix}_BRIDGE_PORT", "18812")
        try:
            port = int(port_raw)
        except ValueError as exc:
            # Surface bad env values as MT5ConnectionError so the CLI's
            # try/except path emits structured JSON instead of a raw
            # Python traceback. ``ValueError`` is the only failure mode
            # for ``int()`` we can hit on user-supplied env values.
            raise MT5ConnectionError(
                f"{prefix}_BRIDGE_PORT must be an integer, got {port_raw!r}"
            ) from exc
        login_raw = os.environ.get(f"{prefix}_DEMO_LOGIN") or os.environ.get(f"{prefix}_LOGIN")
        password = os.environ.get(f"{prefix}_DEMO_PASSWORD") or os.environ.get(f"{prefix}_PASSWORD")
        server = os.environ.get(f"{prefix}_DEMO_SERVER") or os.environ.get(f"{prefix}_SERVER")
        try:
            login = int(login_raw) if login_raw else None
        except ValueError as exc:
            raise MT5ConnectionError(
                f"{prefix}_DEMO_LOGIN / {prefix}_LOGIN must be an integer, got {login_raw!r}"
            ) from exc
        return cls(host=host, port=port, login=login, password=password, server=server)


class _RemoteMT5Module(Protocol):
    """Minimal subset of the ``MetaTrader5`` module surface we use."""

    def initialize(
        self,
        *,
        login: int | None = ...,
        password: str | None = ...,
        server: str | None = ...,
        timeout: int | None = ...,
    ) -> bool: ...

    def shutdown(self) -> None: ...

    def last_error(self) -> tuple[int, str]: ...

    def terminal_info(self) -> Any | None: ...

    def account_info(self) -> Any | None: ...

    def symbol_info(self, symbol: str) -> Any | None: ...

    def symbol_info_tick(self, symbol: str) -> Any | None: ...

    def copy_rates_from_pos(
        self, symbol: str, timeframe: int, start_pos: int, count: int
    ) -> Any | None: ...

    def positions_get(self, *, symbol: str | None = ...) -> Sequence[Any] | None: ...

    def order_check(self, request: dict[str, Any]) -> Any | None: ...


_TIMEFRAME_NAMES = {
    "M1": "TIMEFRAME_M1",
    "M5": "TIMEFRAME_M5",
    "M15": "TIMEFRAME_M15",
    "M30": "TIMEFRAME_M30",
    "H1": "TIMEFRAME_H1",
    "H4": "TIMEFRAME_H4",
    "D1": "TIMEFRAME_D1",
}

# Attribute names of MT5 enum constants we use when building a trade
# request. The strings here are *attribute names on the remote module*,
# not protocol values: :meth:`MT5Client.order_check` resolves each one
# via ``getattr(remote_mt5, name)`` to the integer the broker actually
# expects. Callers should always pass strings — never assume an integer.
ORDER_TYPE_BUY = "ORDER_TYPE_BUY"
ORDER_TYPE_SELL = "ORDER_TYPE_SELL"
TRADE_ACTION_DEAL = "TRADE_ACTION_DEAL"

# Request fields whose values are MT5 enum constants and therefore need
# attribute-name -> integer resolution before being sent over RPyC.
_ENUM_REQUEST_FIELDS = ("action", "type", "type_time", "type_filling")


class MT5Client:
    """RPyC-backed client for the remote ``MetaTrader5`` module.

    The constructor does **not** open a connection. Use :meth:`connect`
    explicitly so callers can decide how to handle outages.

    Tests can pass a pre-built ``mt5_module`` (any object satisfying the
    :class:`_RemoteMT5Module` Protocol) to bypass RPyC entirely.
    """

    def __init__(
        self,
        config: MT5BridgeConfig,
        *,
        mt5_module: _RemoteMT5Module | None = None,
    ) -> None:
        self._config = config
        self._conn: Any | None = None
        self._mt5: _RemoteMT5Module | None = mt5_module

    @property
    def config(self) -> MT5BridgeConfig:
        return self._config

    @property
    def is_connected(self) -> bool:
        return self._mt5 is not None

    def connect(self) -> None:
        """Open RPyC connection and call ``initialize`` on the bridge."""
        if self._mt5 is not None:
            return  # already wired (e.g. test fake)
        try:
            import rpyc
        except ImportError as exc:  # pragma: no cover - depends on optional install
            raise MT5ConnectionError(
                "rpyc is not installed; install with `uv sync --extra mt5`"
            ) from exc

        try:
            self._conn = rpyc.classic.connect(self._config.host, self._config.port)
        except (ConnectionRefusedError, OSError) as exc:
            raise MT5ConnectionError(
                f"cannot reach mt5linux bridge at {self._config.host}:{self._config.port}: {exc}"
            ) from exc

        # Once self._conn is open, every failure path below MUST close it
        # to avoid leaking sockets — repeated snapshot()/preflight() calls
        # against a half-working bridge would otherwise pile up RPyC
        # channels with no handle to clean them up.
        try:
            try:
                mt5 = self._conn.modules.MetaTrader5
            except Exception as exc:  # pragma: no cover - depends on remote env
                raise MT5ConnectionError(
                    "remote bridge does not expose `MetaTrader5` module"
                ) from exc

            ok = mt5.initialize(
                login=self._config.login,
                password=self._config.password,
                server=self._config.server,
                timeout=self._config.timeout_ms,
            )
            if not ok:
                err = mt5.last_error()
                raise MT5ConnectionError(f"MT5 initialize() failed: {err}")
            self._mt5 = mt5
        except BaseException:
            with contextlib.suppress(Exception):
                self._conn.close()
            self._conn = None
            raise
        _log.info(
            "mt5.connect.ok",
            host=self._config.host,
            port=self._config.port,
            server=self._config.server,
            login=self._config.login,
        )

    def disconnect(self) -> None:
        if self._mt5 is not None:
            with contextlib.suppress(Exception):  # pragma: no cover - best-effort teardown
                self._mt5.shutdown()
            self._mt5 = None
        if self._conn is not None:
            with contextlib.suppress(Exception):  # pragma: no cover - best-effort teardown
                self._conn.close()
            self._conn = None

    def __enter__(self) -> MT5Client:
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.disconnect()

    # -- read surface -------------------------------------------------------

    def _ensure(self) -> _RemoteMT5Module:
        if self._mt5 is None:
            raise MT5ConnectionError("MT5Client is not connected; call connect() first")
        return self._mt5

    def terminal_info(self) -> Any:
        info = self._ensure().terminal_info()
        if info is None:
            err = self._ensure().last_error()
            raise MT5ConnectionError(f"terminal_info() returned None: {err}")
        return info

    def account_info(self) -> Any:
        info = self._ensure().account_info()
        if info is None:
            err = self._ensure().last_error()
            raise MT5ConnectionError(f"account_info() returned None: {err}")
        return info

    def symbol_info(self, symbol: str) -> Any:
        info = self._ensure().symbol_info(symbol)
        if info is None:
            err = self._ensure().last_error()
            raise MT5ConnectionError(f"symbol_info({symbol!r}) returned None: {err}")
        return info

    def symbol_info_tick(self, symbol: str) -> Any:
        tick = self._ensure().symbol_info_tick(symbol)
        if tick is None:
            err = self._ensure().last_error()
            raise MT5ConnectionError(f"symbol_info_tick({symbol!r}) returned None: {err}")
        return tick

    def copy_rates_from_pos(
        self, *, symbol: str, timeframe: str, start_pos: int = 0, count: int
    ) -> list[dict[str, Any]]:
        """Fetch ``count`` bars ending at the most recent fully-closed bar.

        ``start_pos=1`` means the request starts at the bar **before** the
        currently-forming Running Bar, which matches the Closed Bar
        invariant baked into the rest of the pipeline.
        """
        if timeframe not in _TIMEFRAME_NAMES:
            raise ValueError(f"unsupported timeframe: {timeframe}")
        mt5 = self._ensure()
        tf_value = getattr(mt5, _TIMEFRAME_NAMES[timeframe])
        rates = mt5.copy_rates_from_pos(symbol, tf_value, start_pos, count)
        if rates is None:
            err = mt5.last_error()
            raise MT5ConnectionError(f"copy_rates_from_pos failed: {err}")
        # Each row is a numpy.void (structured-array record). Access via
        # ``row["field"]`` only — numpy.void does not support ``.get()``.
        # MT5 always populates ``time``, ``open/high/low/close``,
        # ``tick_volume`` and ``spread`` for the timeframes we use.
        return [
            {
                "open_time": datetime.fromtimestamp(int(row["time"]), tz=UTC),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["tick_volume"]),
                "spread_points": int(row["spread"]),
            }
            for row in rates
        ]

    def positions(self, *, symbol: str | None = None) -> list[dict[str, Any]]:
        mt5 = self._ensure()
        rows = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
        if rows is None:
            return []
        return [
            {
                "ticket": int(p.ticket),
                "symbol": str(p.symbol),
                "type": int(p.type),  # 0=BUY, 1=SELL per MT5 convention
                "volume": float(p.volume),
                "price_open": float(p.price_open),
                "sl": float(p.sl),
                "tp": float(p.tp),
                "magic": int(p.magic),
                "comment": str(p.comment),
                "time": datetime.fromtimestamp(int(p.time), tz=UTC),
            }
            for p in rows
        ]

    # -- write-equivalent (still safe — order_check is dry-run) ------------

    def _resolve_enum_request(self, request: dict[str, Any]) -> dict[str, Any]:
        """Replace string enum names in ``request`` with the broker's int values.

        MT5 expects integer constants on the wire (e.g. ``mt5.TRADE_ACTION_DEAL = 1``),
        but callers in this codebase pass attribute-name strings so the
        request payload survives in audit JSON unambiguously. This helper
        looks up each enum field on the remote module via ``getattr`` —
        the same trick :meth:`copy_rates_from_pos` uses for timeframes.
        Unknown fields and non-string values pass through untouched so
        callers can still pre-resolve constants if they want to.
        """
        mt5 = self._ensure()
        resolved = dict(request)
        for field in _ENUM_REQUEST_FIELDS:
            value = resolved.get(field)
            if isinstance(value, str):
                if not hasattr(mt5, value):
                    raise ValueError(f"unknown MT5 constant {value!r} for request field {field!r}")
                resolved[field] = getattr(mt5, value)
        return resolved

    def order_check(self, request: dict[str, Any]) -> dict[str, Any]:
        """Server-side validation of an order request — never executes.

        ``order_check`` is the only "trade" surface we expose: it asks the
        broker whether the request would be accepted, so it is suitable
        for the dry_run preflight in issue #3.
        """
        mt5 = self._ensure()
        result = mt5.order_check(self._resolve_enum_request(request))
        if result is None:
            err = mt5.last_error()
            raise MT5ConnectionError(f"order_check() returned None: {err}")
        return {
            "retcode": int(result.retcode),
            "comment": str(result.comment),
            "balance": float(result.balance),
            "equity": float(result.equity),
            "profit": float(result.profit),
            "margin": float(result.margin),
            "margin_free": float(result.margin_free),
            "margin_level": float(result.margin_level),
        }
