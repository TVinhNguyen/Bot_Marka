"""Tests for MT5BridgeStatus — must satisfy the MT5StatusProvider contract:
implementations MUST NOT raise. Failures are reported via
``connected=False`` + a descriptive ``detail`` string.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ai_mt5.mt5.client import MT5BridgeConfig, MT5Client, MT5ConnectionError
from ai_mt5.mt5.status import MT5BridgeStatus


class _Account:
    login = 5050098604
    server = "MetaQuotes-Demo"


class _OkClient:
    def __init__(self) -> None:
        self.connected = False
        self.disconnected = False

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.disconnected = True

    def account_info(self) -> Any:
        return _Account()

    def positions(self, *, symbol: str | None = None) -> list[dict[str, Any]]:
        return [{"ticket": 1}, {"ticket": 2}]

    def symbol_info_tick(self, symbol: str) -> Any:
        class _Tick:
            time = int(datetime(2026, 4, 30, 12, 0, tzinfo=UTC).timestamp())

        return _Tick()


def _bridge_status(client: Any) -> MT5BridgeStatus:
    """Build a MT5BridgeStatus around an arbitrary client-shaped object.

    MT5BridgeStatus only invokes the duck-typed methods we need, so a
    MT5Client subclass is overkill — we hand it any object with
    connect/disconnect/account_info/positions/symbol_info_tick.
    """
    holder = MT5Client(MT5BridgeConfig(host="localhost"))
    # Replace the inner client surface with our fake.
    holder.connect = client.connect  # type: ignore[method-assign]
    holder.disconnect = client.disconnect  # type: ignore[method-assign]
    holder.account_info = client.account_info  # type: ignore[method-assign]
    holder.positions = client.positions  # type: ignore[method-assign]
    holder.symbol_info_tick = client.symbol_info_tick  # type: ignore[method-assign]
    return MT5BridgeStatus(holder, watch_symbol="EURUSD")


def test_snapshot_happy_path_reports_connected() -> None:
    client = _OkClient()
    status = _bridge_status(client)
    snap = status.snapshot(now=datetime(2026, 4, 30, 12, 0, tzinfo=UTC))
    assert snap.connected is True
    assert snap.open_positions == 2
    assert snap.last_tick_at == datetime(2026, 4, 30, 12, 0, tzinfo=UTC)
    assert "login=5050098604" in snap.detail
    assert client.disconnected is True  # snapshot must not leak the connection


def test_snapshot_swallows_mt5_connection_error_on_connect() -> None:
    class _BadClient(_OkClient):
        def connect(self) -> None:
            raise MT5ConnectionError("bridge offline")

    client = _BadClient()
    snap = _bridge_status(client).snapshot(now=datetime(2026, 4, 30, tzinfo=UTC))
    assert snap.connected is False
    assert "bridge unreachable" in snap.detail


def test_snapshot_swallows_arbitrary_exception_on_connect() -> None:
    """Regression: MT5StatusProvider.snapshot MUST NOT raise. RPyC + remote
    MT5 errors can surface as EOFError / ConnectionResetError / generic
    Exception, none of which inherit from MT5ConnectionError."""

    class _BadClient(_OkClient):
        def connect(self) -> None:
            raise EOFError("rpyc channel dropped")

    client = _BadClient()
    snap = _bridge_status(client).snapshot(now=datetime(2026, 4, 30, tzinfo=UTC))
    assert snap.connected is False
    assert "bridge unreachable" in snap.detail
    assert "rpyc channel dropped" in snap.detail


def test_snapshot_swallows_arbitrary_exception_mid_snapshot() -> None:
    """Regression: a mid-snapshot RPyC drop MUST NOT propagate."""

    class _MidFailClient(_OkClient):
        def positions(self, *, symbol: str | None = None) -> list[dict[str, Any]]:
            raise ConnectionResetError("bridge dropped after account_info")

    client = _MidFailClient()
    snap = _bridge_status(client).snapshot(now=datetime(2026, 4, 30, tzinfo=UTC))
    assert snap.connected is False
    assert "snapshot failed" in snap.detail
    assert client.disconnected is True  # cleanup runs even on exception


def test_snapshot_disconnects_on_success() -> None:
    """Each snapshot opens its own connection — verify it is closed too."""
    client = _OkClient()
    _bridge_status(client).snapshot(now=datetime(2026, 4, 30, tzinfo=UTC))
    assert client.disconnected is True
