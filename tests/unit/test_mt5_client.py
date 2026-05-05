"""Unit tests for the MT5 RPyC client wrapper.

These tests never touch RPyC or a real broker — they exercise the typed
surface in :class:`MT5Client` against a hand-rolled fake module that
mimics the small subset of ``MetaTrader5`` the bot actually uses.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pytest

from ai_mt5.mt5.client import MT5BridgeConfig, MT5Client, MT5ConnectionError

# Pretend constants that mimic the MT5 module attributes.
_FAKE_TIMEFRAMES = {"TIMEFRAME_M15": 15}


@dataclass
class _Tick:
    time: int
    bid: float
    ask: float


@dataclass
class _Symbol:
    visible: bool = True
    trade_mode: int = 1
    point: float = 0.00001


@dataclass
class _Account:
    login: int = 5050098604
    server: str = "MetaQuotes-Demo"
    currency: str = "USD"
    balance: float = 10_000.0
    equity: float = 10_000.0
    trade_allowed: bool = True


@dataclass
class _Terminal:
    connected: bool = True
    trade_allowed: bool = True
    name: str = "MetaTrader 5"


@dataclass
class _Position:
    ticket: int
    symbol: str
    type: int
    volume: float
    price_open: float
    sl: float
    tp: float
    magic: int
    comment: str
    time: int


@dataclass
class _OrderCheckResult:
    retcode: int = 10009  # TRADE_RETCODE_DONE
    comment: str = "ok"
    balance: float = 10_000.0
    equity: float = 10_000.0
    profit: float = 0.0
    margin: float = 100.0
    margin_free: float = 9_900.0
    margin_level: float = 9_900.0


_FAKE_ENUM_CONSTS = {
    "TRADE_ACTION_DEAL": 1,
    "ORDER_TYPE_BUY": 0,
    "ORDER_TYPE_SELL": 1,
    "ORDER_TIME_GTC": 0,
    "ORDER_FILLING_IOC": 1,
}


class _FakeMT5:
    """In-memory stand-in for the remote ``MetaTrader5`` module."""

    def __init__(self) -> None:
        self.last_error_value: tuple[int, str] = (0, "ok")
        self.initialize_called_with: dict[str, Any] = {}
        self.shutdown_called: bool = False
        self.bars: list[dict[str, Any]] = []
        self.positions_value: list[_Position] = []
        self.next_order_check: _OrderCheckResult | None = _OrderCheckResult()
        self.symbols: dict[str, _Symbol] = {"EURUSD": _Symbol()}
        self.last_order_check_request: dict[str, Any] | None = None
        # Expose constants like the real package does.
        for name, value in _FAKE_TIMEFRAMES.items():
            setattr(self, name, value)
        for name, value in _FAKE_ENUM_CONSTS.items():
            setattr(self, name, value)

    def initialize(self, **kwargs: Any) -> bool:
        self.initialize_called_with = kwargs
        return True

    def shutdown(self) -> None:
        self.shutdown_called = True

    def last_error(self) -> tuple[int, str]:
        return self.last_error_value

    def terminal_info(self) -> _Terminal:
        return _Terminal()

    def account_info(self) -> _Account:
        return _Account()

    def symbol_info(self, symbol: str) -> _Symbol:
        return self.symbols[symbol]

    def symbol_info_tick(self, symbol: str) -> _Tick:
        return _Tick(time=int(datetime(2026, 4, 30, 13, 0).timestamp()), bid=1.07, ask=1.0701)

    def copy_rates_from_pos(
        self, symbol: str, timeframe: int, start_pos: int, count: int
    ) -> list[dict[str, Any]] | None:
        return self.bars[start_pos : start_pos + count] if self.bars else []

    def positions_get(self, *, symbol: str | None = None) -> list[_Position]:
        if symbol is None:
            return list(self.positions_value)
        return [p for p in self.positions_value if p.symbol == symbol]

    def order_check(self, request: dict[str, Any]) -> _OrderCheckResult | None:
        self.last_order_check_request = request
        return self.next_order_check


def test_from_env_reads_required_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MT5_BRIDGE_HOST", "192.168.0.50")
    monkeypatch.setenv("MT5_BRIDGE_PORT", "18900")
    monkeypatch.setenv("MT5_DEMO_LOGIN", "5050098604")
    monkeypatch.setenv("MT5_DEMO_PASSWORD", "secret")
    monkeypatch.setenv("MT5_DEMO_SERVER", "MetaQuotes-Demo")
    cfg = MT5BridgeConfig.from_env()
    assert cfg.host == "192.168.0.50"
    assert cfg.port == 18900
    assert cfg.login == 5050098604
    assert cfg.password == "secret"
    assert cfg.server == "MetaQuotes-Demo"


def test_from_env_missing_host_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MT5_BRIDGE_HOST", raising=False)
    with pytest.raises(MT5ConnectionError):
        MT5BridgeConfig.from_env()


def test_client_skips_connect_when_module_injected() -> None:
    fake = _FakeMT5()
    client = MT5Client(MT5BridgeConfig(host="localhost"), mt5_module=fake)
    assert client.is_connected
    # No RPyC call attempted because the module is already wired.
    client.connect()
    assert fake.initialize_called_with == {}


def test_disconnect_clears_module_and_calls_shutdown() -> None:
    fake = _FakeMT5()
    client = MT5Client(MT5BridgeConfig(host="localhost"), mt5_module=fake)
    client.disconnect()
    assert fake.shutdown_called
    assert not client.is_connected


def test_copy_rates_from_pos_returns_typed_dicts() -> None:
    fake = _FakeMT5()
    fake.bars = [
        {
            "time": int(datetime(2026, 4, 30, 12, 0).timestamp()),
            "open": 1.07,
            "high": 1.071,
            "low": 1.069,
            "close": 1.0705,
            "tick_volume": 1234,
            "spread": 12,
        }
    ]
    client = MT5Client(MT5BridgeConfig(host="localhost"), mt5_module=fake)
    bars = client.copy_rates_from_pos(symbol="EURUSD", timeframe="M15", start_pos=0, count=10)
    assert len(bars) == 1
    bar = bars[0]
    assert isinstance(bar["open_time"], datetime)
    assert bar["spread_points"] == 12
    assert bar["volume"] == 1234.0


def test_copy_rates_works_with_numpy_structured_array() -> None:
    """Regression: real MT5 returns numpy structured arrays whose rows are
    ``numpy.void``. Those rows do NOT support ``.get()`` — only ``row["field"]``."""
    import numpy as np

    dtype = np.dtype(
        [
            ("time", "<i8"),
            ("open", "<f8"),
            ("high", "<f8"),
            ("low", "<f8"),
            ("close", "<f8"),
            ("tick_volume", "<i8"),
            ("spread", "<i4"),
            ("real_volume", "<i8"),
        ]
    )
    arr = np.array(
        [
            (
                int(datetime(2026, 4, 30, 12, 0).timestamp()),
                1.07,
                1.071,
                1.069,
                1.0705,
                4321,
                15,
                0,
            )
        ],
        dtype=dtype,
    )
    fake = _FakeMT5()
    fake.bars = arr  # Override with the real-shape numpy array.
    client = MT5Client(MT5BridgeConfig(host="localhost"), mt5_module=fake)
    bars = client.copy_rates_from_pos(symbol="EURUSD", timeframe="M15", start_pos=0, count=10)
    assert len(bars) == 1
    assert bars[0]["volume"] == 4321.0
    assert bars[0]["spread_points"] == 15


def test_copy_rates_unsupported_timeframe_raises() -> None:
    fake = _FakeMT5()
    client = MT5Client(MT5BridgeConfig(host="localhost"), mt5_module=fake)
    with pytest.raises(ValueError, match="unsupported timeframe"):
        client.copy_rates_from_pos(symbol="EURUSD", timeframe="W1", start_pos=0, count=10)


def test_positions_returns_dict_list() -> None:
    fake = _FakeMT5()
    fake.positions_value = [
        _Position(
            ticket=1,
            symbol="EURUSD",
            type=0,
            volume=0.10,
            price_open=1.07,
            sl=1.06,
            tp=1.08,
            magic=26042901,
            comment="ai-mt5-mm",
            time=int(datetime(2026, 4, 30, 12, 0).timestamp()),
        )
    ]
    client = MT5Client(MT5BridgeConfig(host="localhost"), mt5_module=fake)
    pos = client.positions()
    assert pos == [
        {
            "ticket": 1,
            "symbol": "EURUSD",
            "type": 0,
            "volume": 0.1,
            "price_open": 1.07,
            "sl": 1.06,
            "tp": 1.08,
            "magic": 26042901,
            "comment": "ai-mt5-mm",
            "time": pos[0]["time"],
        }
    ]


def test_order_check_returns_typed_dict() -> None:
    fake = _FakeMT5()
    client = MT5Client(MT5BridgeConfig(host="localhost"), mt5_module=fake)
    result = client.order_check(
        {
            "action": "TRADE_ACTION_DEAL",
            "symbol": "EURUSD",
            "volume": 0.01,
            "type": "ORDER_TYPE_BUY",
            "price": 1.07,
        }
    )
    assert result["retcode"] == 10009
    assert result["comment"] == "ok"


def test_order_check_resolves_string_enum_names_to_ints() -> None:
    """The MT5 broker rejects string enum names — MT5Client must resolve them."""
    fake = _FakeMT5()
    client = MT5Client(MT5BridgeConfig(host="localhost"), mt5_module=fake)
    client.order_check(
        {
            "action": "TRADE_ACTION_DEAL",
            "symbol": "EURUSD",
            "volume": 0.01,
            "type": "ORDER_TYPE_BUY",
            "price": 1.07,
            "type_time": "ORDER_TIME_GTC",
            "type_filling": "ORDER_FILLING_IOC",
        }
    )
    forwarded = fake.last_order_check_request
    assert forwarded is not None
    # All four enum fields must have been resolved to the int constants
    # the remote module exposes (string names would break a real broker).
    assert forwarded["action"] == _FAKE_ENUM_CONSTS["TRADE_ACTION_DEAL"]
    assert forwarded["type"] == _FAKE_ENUM_CONSTS["ORDER_TYPE_BUY"]
    assert forwarded["type_time"] == _FAKE_ENUM_CONSTS["ORDER_TIME_GTC"]
    assert forwarded["type_filling"] == _FAKE_ENUM_CONSTS["ORDER_FILLING_IOC"]
    # Pass-through fields stay untouched.
    assert forwarded["symbol"] == "EURUSD"
    assert forwarded["volume"] == 0.01
    assert forwarded["price"] == 1.07


def test_order_check_rejects_unknown_constant_name() -> None:
    fake = _FakeMT5()
    client = MT5Client(MT5BridgeConfig(host="localhost"), mt5_module=fake)
    with pytest.raises(ValueError, match="unknown MT5 constant"):
        client.order_check(
            {
                "action": "TRADE_ACTION_BOGUS",
                "symbol": "EURUSD",
                "volume": 0.01,
                "type": "ORDER_TYPE_BUY",
                "price": 1.07,
            }
        )


def test_order_check_passes_int_values_through() -> None:
    """Pre-resolved int values should not be re-resolved (idempotent)."""
    fake = _FakeMT5()
    client = MT5Client(MT5BridgeConfig(host="localhost"), mt5_module=fake)
    client.order_check(
        {
            "action": 1,
            "symbol": "EURUSD",
            "volume": 0.01,
            "type": 0,
            "price": 1.07,
        }
    )
    forwarded = fake.last_order_check_request
    assert forwarded is not None
    assert forwarded["action"] == 1
    assert forwarded["type"] == 0


def test_methods_raise_when_disconnected() -> None:
    client = MT5Client(MT5BridgeConfig(host="localhost"))
    with pytest.raises(MT5ConnectionError):
        client.account_info()
    with pytest.raises(MT5ConnectionError):
        client.terminal_info()


def test_connect_without_rpyc_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Connecting with no bridge installed must surface MT5ConnectionError."""
    client = MT5Client(MT5BridgeConfig(host="0.0.0.0", port=1))
    # Force the import-time check to fail no matter what the host has.
    import builtins

    real_import = builtins.__import__

    def deny_rpyc(name: str, *args: Any, **kwargs: Any):
        if name == "rpyc":
            raise ImportError("no rpyc here")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", deny_rpyc)
    with pytest.raises(MT5ConnectionError, match="rpyc is not installed"):
        client.connect()


def test_connect_closes_rpyc_conn_when_initialize_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: a partial connect() must not leak the RPyC socket.

    When ``rpyc.classic.connect`` succeeds but ``MetaTrader5.initialize``
    fails (terminal logged out, account locked, …), the underlying RPyC
    channel must be closed before the exception leaves connect(). Repeated
    health snapshots against a half-working bridge otherwise leak one
    socket per snapshot.
    """

    class _FailingMT5:
        def initialize(self, **_: Any) -> bool:
            return False

        def last_error(self) -> tuple[int, str]:
            return (-1, "logged out")

    closed: list[bool] = []

    class _FakeRpycConn:
        def __init__(self) -> None:
            class _Modules:
                MetaTrader5 = _FailingMT5()

            self.modules = _Modules()

        def close(self) -> None:
            closed.append(True)

    fake_conn = _FakeRpycConn()

    class _FakeRpyc:
        class classic:  # noqa: N801 - mirroring rpyc.classic
            @staticmethod
            def connect(_host: str, _port: int) -> _FakeRpycConn:
                return fake_conn

    import sys

    monkeypatch.setitem(sys.modules, "rpyc", _FakeRpyc)
    client = MT5Client(MT5BridgeConfig(host="bridge", port=12345))
    with pytest.raises(MT5ConnectionError, match="initialize"):
        client.connect()
    assert closed == [True], "RPyC connection was not closed on initialize() failure"
    assert not client.is_connected


def test_environ_isolation_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """from_env should respect MT5_LOGIN / MT5_PASSWORD as fallbacks."""
    for k in (
        "MT5_DEMO_LOGIN",
        "MT5_DEMO_PASSWORD",
        "MT5_DEMO_SERVER",
        "MT5_LOGIN",
        "MT5_PASSWORD",
        "MT5_SERVER",
        "MT5_BRIDGE_PORT",
    ):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("MT5_BRIDGE_HOST", "host")
    monkeypatch.setenv("MT5_LOGIN", "1")
    monkeypatch.setenv("MT5_PASSWORD", "p")
    monkeypatch.setenv("MT5_SERVER", "S")
    cfg = MT5BridgeConfig.from_env()
    assert cfg.login == 1
    assert cfg.password == "p"
    assert cfg.server == "S"
    assert cfg.port == 18812


def test_required_env_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run with no MT5 vars set to confirm pyproject.toml extras are not required for this test."""
    for k in list(os.environ):
        if k.startswith("MT5_"):
            monkeypatch.delenv(k, raising=False)
    with pytest.raises(MT5ConnectionError):
        MT5BridgeConfig.from_env()
