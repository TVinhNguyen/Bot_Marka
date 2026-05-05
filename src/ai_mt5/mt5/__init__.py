"""MetaTrader 5 bridge client and adapters.

This module connects this Linux host to a Windows-side ``mt5linux`` RPyC
bridge. The official ``MetaTrader5`` Python package is Windows-only; the
bridge keeps the Windows-only surface on the Windows machine and lets us
run our orchestrator from Linux.

Public surface:

* :class:`MT5BridgeConfig` — connection config (host, port, login, server, …).
* :class:`MT5Client` — thin RPyC wrapper around the remote ``MetaTrader5`` module.
* :class:`MT5BridgeStatus` — :class:`~ai_mt5.observability.health.MT5StatusProvider`
  implementation backed by an :class:`MT5Client`.
* :class:`MT5ConnectionError` — raised when the bridge or terminal is unreachable.
"""

from .client import MT5BridgeConfig, MT5Client, MT5ConnectionError
from .status import MT5BridgeStatus

__all__ = [
    "MT5BridgeConfig",
    "MT5BridgeStatus",
    "MT5Client",
    "MT5ConnectionError",
]
