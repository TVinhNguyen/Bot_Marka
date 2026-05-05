"""Unit tests for the issue #3 preflight against a fake MT5 module."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from ai_mt5.config.models import AppConfig
from ai_mt5.mt5.client import MT5BridgeConfig, MT5Client
from ai_mt5.mt5.preflight import RETCODE_DONE, run_preflight


def _now() -> datetime:
    return datetime(2026, 4, 30, 13, 30, tzinfo=UTC)


def _seed_bars(n: int = 250) -> list[dict[str, Any]]:
    base = _now() - timedelta(minutes=15 * (n + 1))
    return [
        {
            "time": int((base + timedelta(minutes=15 * i)).timestamp()),
            "open": 1.07 + 0.0001 * (i % 5),
            "high": 1.0710 + 0.0001 * (i % 5),
            "low": 1.0690 + 0.0001 * (i % 5),
            "close": 1.0705 + 0.0001 * (i % 5),
            "tick_volume": 1000 + i,
            "spread": 12,
        }
        for i in range(n)
    ]


@dataclass
class _Tick:
    time: int
    bid: float
    ask: float


@dataclass
class _Symbol:
    visible: bool = True
    trade_mode: int = 1


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
class _OrderResult:
    retcode: int = RETCODE_DONE
    comment: str = "ok"
    balance: float = 10_000.0
    equity: float = 10_000.0
    profit: float = 0.0
    margin: float = 100.0
    margin_free: float = 9_900.0
    margin_level: float = 9_900.0


class _FakeMT5:
    TIMEFRAME_M15 = 15
    TRADE_ACTION_DEAL = 1
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    ORDER_TIME_GTC = 0
    ORDER_FILLING_IOC = 1

    def __init__(self) -> None:
        self.bars = _seed_bars()
        self.tick = _Tick(time=int(_now().timestamp()), bid=1.07, ask=1.0701)
        self.terminal = _Terminal()
        self.account = _Account()
        self.symbol = _Symbol()
        self.next_order_check = _OrderResult()
        self.last_order_check_request: dict[str, Any] | None = None

    def initialize(self, **_: Any) -> bool:
        return True

    def shutdown(self) -> None:
        pass

    def last_error(self) -> tuple[int, str]:
        return (0, "ok")

    def terminal_info(self) -> _Terminal:
        return self.terminal

    def account_info(self) -> _Account:
        return self.account

    def symbol_info(self, _symbol: str) -> _Symbol:
        return self.symbol

    def symbol_info_tick(self, _symbol: str) -> _Tick:
        return self.tick

    def copy_rates_from_pos(
        self, _symbol: str, _tf: int, start: int, count: int
    ) -> list[dict[str, Any]]:
        return self.bars[start : start + count]

    def positions_get(self, *, symbol: str | None = None) -> list[Any]:
        return []

    def order_check(self, request: dict[str, Any]) -> _OrderResult:
        self.last_order_check_request = request
        return self.next_order_check


def _client(fake: _FakeMT5) -> MT5Client:
    return MT5Client(MT5BridgeConfig(host="localhost"), mt5_module=fake)


def test_preflight_passes_on_healthy_terminal(app_config: AppConfig) -> None:
    fake = _FakeMT5()
    report = run_preflight(client=_client(fake), config=app_config, now=_now())
    assert report.ok, report.failures
    assert report.bars_received == 200
    assert report.order_check is not None
    assert report.order_check["retcode"] == RETCODE_DONE
    assert report.terminal == {
        "connected": True,
        "trade_allowed": True,
        "name": "MetaTrader 5",
    }


def test_preflight_catches_rpyc_transport_error(app_config: AppConfig) -> None:
    """Regression: RPyC transport errors (EOFError, ConnectionResetError,
    OSError, TimeoutError) raised mid-call when the bridge drops do NOT
    subclass MT5ConnectionError, so they would propagate as a raw Python
    traceback. Preflight must catch these and surface them as a
    bridge_transport_error failure so the operator CLI emits JSON."""
    fake = _FakeMT5()

    def _drop(*_args: Any, **_kwargs: Any) -> Any:
        raise EOFError("RPyC connection reset by peer")

    fake.copy_rates_from_pos = _drop  # type: ignore[method-assign]

    report = run_preflight(client=_client(fake), config=app_config, now=_now())
    assert not report.ok
    assert any(f.startswith("bridge_transport_error:EOFError") for f in report.failures), (
        report.failures
    )


def test_preflight_order_check_comment_respects_31_char_limit(
    app_config: AppConfig,
) -> None:
    """Regression: MT5 caps broker comments at 31 chars. The config
    already allows up to 31, so suffixing "-preflight" must be truncated
    or some brokers will reject the order_check, producing a spurious
    failure that blocks the operator."""
    long_comment = "a" * 31  # max allowed by config
    cfg = app_config.model_copy(
        update={
            "execution": app_config.execution.model_copy(update={"order_comment": long_comment})
        }
    )
    fake = _FakeMT5()
    run_preflight(client=_client(fake), config=cfg, now=_now())
    assert fake.last_order_check_request is not None
    sent_comment = fake.last_order_check_request["comment"]
    assert len(sent_comment) <= 31, f"comment {sent_comment!r} exceeds 31 chars"


def test_preflight_fails_when_terminal_not_trade_allowed(app_config: AppConfig) -> None:
    fake = _FakeMT5()
    fake.terminal = _Terminal(connected=True, trade_allowed=False, name="MetaTrader 5")
    report = run_preflight(client=_client(fake), config=app_config, now=_now())
    assert not report.ok
    assert "trade_not_allowed" in report.failures


def test_preflight_fails_when_account_trade_disabled(app_config: AppConfig) -> None:
    fake = _FakeMT5()
    fake.account = _Account(trade_allowed=False)
    report = run_preflight(client=_client(fake), config=app_config, now=_now())
    assert not report.ok
    assert "account_trade_disabled" in report.failures


def test_preflight_fails_when_symbol_not_visible(app_config: AppConfig) -> None:
    fake = _FakeMT5()
    fake.symbol = _Symbol(visible=False, trade_mode=1)
    report = run_preflight(client=_client(fake), config=app_config, now=_now())
    assert not report.ok
    assert any(f.startswith("symbol_not_visible") for f in report.failures)


def test_preflight_fails_when_symbol_trade_disabled(app_config: AppConfig) -> None:
    fake = _FakeMT5()
    fake.symbol = _Symbol(visible=True, trade_mode=0)
    report = run_preflight(client=_client(fake), config=app_config, now=_now())
    assert not report.ok
    assert any(f.startswith("symbol_trade_disabled") for f in report.failures)


def test_preflight_fails_when_order_check_rejected(app_config: AppConfig) -> None:
    fake = _FakeMT5()
    fake.next_order_check = _OrderResult(retcode=10006, comment="market closed")
    report = run_preflight(client=_client(fake), config=app_config, now=_now())
    assert not report.ok
    assert any(f.startswith("order_check_rejected") for f in report.failures)


def test_preflight_fails_when_no_ask_price(app_config: AppConfig) -> None:
    fake = _FakeMT5()
    fake.tick = _Tick(time=int(_now().timestamp()), bid=0.0, ask=0.0)
    report = run_preflight(client=_client(fake), config=app_config, now=_now())
    assert not report.ok
    assert "symbol_no_ask_price" in report.failures
    # Should never call order_check when ask is invalid.
    assert report.order_check is None


def test_preflight_quality_failures_surface(app_config: AppConfig) -> None:
    """Stale or out-of-order bars from the broker must surface as failures."""
    fake = _FakeMT5()
    # Inject a duplicate timestamp to break monotonicity.
    fake.bars[10]["time"] = fake.bars[9]["time"]
    report = run_preflight(client=_client(fake), config=app_config, now=_now())
    assert not report.ok
    assert any(f.startswith("quality:") for f in report.failures)


def test_preflight_resolves_enum_strings_to_ints_on_wire(app_config: AppConfig) -> None:
    """Regression: the broker receives integer constants, never string names."""
    fake = _FakeMT5()
    run_preflight(client=_client(fake), config=app_config, now=_now())
    request = fake.last_order_check_request
    assert request is not None
    assert request["action"] == fake.TRADE_ACTION_DEAL
    assert request["type"] == fake.ORDER_TYPE_BUY
    assert request["type_time"] == fake.ORDER_TIME_GTC
    assert request["type_filling"] == fake.ORDER_FILLING_IOC
    # Volume and symbol are pass-through.
    assert request["symbol"] == "EURUSD"
    assert request["volume"] == 0.01


def test_preflight_to_dict_round_trip(app_config: AppConfig) -> None:
    fake = _FakeMT5()
    report = run_preflight(client=_client(fake), config=app_config, now=_now())
    payload = report.to_dict()
    assert payload["ok"] is True
    assert payload["symbol"] == "EURUSD"
    assert payload["timeframe"] == "M15"
    assert payload["bars_received"] == 200
    assert payload["order_check"]["retcode"] == RETCODE_DONE
