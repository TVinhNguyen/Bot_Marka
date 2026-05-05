"""MT5StatusProvider implementation backed by an MT5Client."""

from __future__ import annotations

from datetime import UTC, datetime

from ..observability.health import MT5SnapshotData
from ..utils.logging_setup import get_logger
from .client import MT5Client

_log = get_logger("ai_mt5.mt5.status")


class MT5BridgeStatus:
    """Live MT5 status reader for :func:`build_health`.

    A fresh ``MT5Client`` connection is opened per snapshot rather than
    held open between health calls. Health checks are infrequent and a
    long-lived RPyC channel through a flaky home-internet link causes
    more confusion than it saves.
    """

    def __init__(self, client: MT5Client, *, watch_symbol: str | None = None) -> None:
        self._client = client
        self._watch_symbol = watch_symbol

    def snapshot(self, *, now: datetime) -> MT5SnapshotData:
        # MT5StatusProvider contract: MUST NOT raise. RPyC can throw
        # EOFError / ConnectionResetError / OSError when the bridge
        # drops mid-call, plus arbitrary remote-module errors, so we
        # catch broadly and report failures via connected=False.
        try:
            self._client.connect()
        except Exception as exc:
            return MT5SnapshotData(
                connected=False,
                open_positions=0,
                last_tick_at=None,
                detail=f"bridge unreachable: {exc}",
            )
        try:
            account = self._client.account_info()
            positions = self._client.positions()
            last_tick_at: datetime | None = None
            if self._watch_symbol is not None:
                tick = self._client.symbol_info_tick(self._watch_symbol)
                if tick is not None and getattr(tick, "time", None):
                    last_tick_at = datetime.fromtimestamp(int(tick.time), tz=UTC)
            return MT5SnapshotData(
                connected=True,
                open_positions=len(positions),
                last_tick_at=last_tick_at,
                detail=f"login={getattr(account, 'login', '?')} server={getattr(account, 'server', '?')}",
            )
        except Exception as exc:
            _log.warning("mt5.status.snapshot_failed", error=str(exc))
            return MT5SnapshotData(
                connected=False,
                open_positions=0,
                last_tick_at=None,
                detail=f"snapshot failed: {exc}",
            )
        finally:
            self._client.disconnect()
