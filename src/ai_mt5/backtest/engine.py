"""Walk-forward backtest engine.

Runs the same Baseline + Model Adapters + Ensemble + Risk Decision pipeline
used by the dry_run tick over a static :class:`Bar` series, with no MT5
involvement. The engine is deterministic by construction:

* Adapters are anti-leak (history strictly before the decision bar).
* Replay never reads bars at indices ``> decision_idx`` until exit.
* All randomness is forbidden -- adapters and the ensemble take pure inputs.

Per issue #10, three pipelines run in parallel over the same bars so the
report can compare them:

1. ``baseline``  -- Baseline adapter only (no ensemble).
2. ``ensemble``  -- All adapters fed through :class:`Ensemble`.
3. Per-adapter   -- Each registered adapter on its own (debug aid).

All pipelines share the same Risk gate, sizing math, cost model, and
trade simulator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

from ..baseline.adapter import BaselineAdapter
from ..config.models import ExecutionConfig, RiskConfig
from ..data.features import build_features
from ..domain.bar import Bar
from ..domain.forecast import Forecast, MetaSignal
from ..domain.market import AccountSnapshot, MarketSnapshot
from ..ensemble.ensemble import Ensemble, EnsembleConfig
from ..models.protocol import AdapterError, ModelAdapter
from ..risk.kill_switch import KillSwitch
from ..risk.manager import RiskManager
from .cost_model import CostModel
from .replay import SimulatedFill, estimate_atr, simulate_trade
from .windows import WalkForwardWindow

PipelineName = Literal["baseline", "ensemble"]


@dataclass(frozen=True)
class BacktestConfig:
    """Tunables for the engine.

    Attributes:
        initial_equity: Starting deposit-currency balance.
        warmup_bars: Minimum number of bars before the first decision.
            Lines up with the Baseline's SMA-20 default (21).
        atr_window: Number of bars used for the ATR estimate fed to
            :func:`compute_sl_tp`.
        bar_seconds: Seconds per bar; used for annualisation of Sharpe and
            for nights-held bookkeeping.
        timeframe: Symbol timeframe label, e.g. ``"M15"``.
        symbol: Symbol name, e.g. ``"EURUSD"``.
        magic / order_comment: Forwarded to :class:`RiskManager`.
        ensemble_config: Optional override of :class:`EnsembleConfig`.
        cost_model: :class:`CostModel` instance shared by every fill.
        risk: Hard risk band; reuses :class:`RiskConfig` so the backtest
            and the live tick are always sized consistently.
    """

    symbol: str
    timeframe: str
    initial_equity: float
    risk: RiskConfig
    cost_model: CostModel
    warmup_bars: int = 21
    atr_window: int = 14
    bar_seconds: float = 900.0  # M15 default
    magic: int = 11_000
    order_comment: str = "ai_mt5_backtest"
    ensemble_config: EnsembleConfig | None = None

    @property
    def bars_per_year(self) -> float:
        # 365 * 24 * 3600 / bar_seconds; trading sessions are accounted for
        # by feeding the engine only bars actually present (weekends usually
        # absent from broker history), so we annualise on bar density alone.
        return (365.0 * 24.0 * 3600.0) / max(self.bar_seconds, 1.0)


@dataclass(frozen=True)
class TradeRecord:
    """A trade as seen by the report layer (post-cost)."""

    pipeline: PipelineName
    fill: SimulatedFill
    gross_price_pnl: float
    cost: float
    net_pnl: float
    contract_size: float
    decision_idx: int
    decision_time: str
    confidence: float
    agreement: float
    final_score: float


@dataclass
class _PipelineState:
    """Mutable per-pipeline accounting; engine-internal."""

    name: PipelineName
    equity: float
    trades: list[TradeRecord] = field(default_factory=list)
    open_until: int = -1  # exclusive index past which the pipeline is free again
    decisions: int = 0
    rejections: int = 0
    veto_count: int = 0


class WalkForwardEngine:
    """Run the full pipeline over a list of bars and aggregate results."""

    def __init__(
        self,
        config: BacktestConfig,
        *,
        adapters: list[ModelAdapter],
        baseline: BaselineAdapter | None = None,
    ) -> None:
        self._cfg = config
        self._baseline = baseline or BaselineAdapter()
        # Ensure the baseline is always part of the ensemble feed for parity
        # with the dry_run tick wiring.
        names = {a.name for a in adapters}
        if self._baseline.name not in names:
            adapters = [*adapters, self._baseline]
        self._adapters = adapters
        self._ensemble = Ensemble(config.ensemble_config)
        self._kill = _StubKillSwitch()

    # -- public --------------------------------------------------------------

    def run_window(
        self, bars: list[Bar], window: WalkForwardWindow
    ) -> dict[PipelineName, _PipelineState]:
        """Run baseline + ensemble pipelines over ``window.oos`` of ``bars``.

        Returns a dict mapping pipeline name -> mutable state. Callers
        snapshot whatever they need from the trades list immediately;
        the engine does not retain state across calls.
        """
        states: dict[PipelineName, _PipelineState] = {
            "baseline": _PipelineState(name="baseline", equity=self._cfg.initial_equity),
            "ensemble": _PipelineState(name="ensemble", equity=self._cfg.initial_equity),
        }
        oos_end = window.oos.end
        risk = RiskManager(
            self._cfg.risk,
            self._kill,
            magic=self._cfg.magic,
            order_comment=self._cfg.order_comment,
        )
        for i in range(window.oos.start, window.oos.end):
            if i < self._cfg.warmup_bars:
                continue
            history = bars[: i + 1]
            decision_bar = bars[i]
            forecasts: dict[str, Forecast] = {}
            for adapter in self._adapters:
                try:
                    features = build_features(history[:-1], decision_bar=history[-1])
                    forecasts[adapter.name] = adapter.forecast(
                        features, symbol=self._cfg.symbol, timeframe=self._cfg.timeframe
                    )
                except AdapterError:
                    continue
                except ValueError:
                    # build_features rejects empty history; skip until warmup.
                    continue

            # Baseline pipeline: only the baseline forecast.
            baseline_forecast = forecasts.get(self._baseline.name)
            if baseline_forecast is not None:
                self._step_pipeline(
                    bars=bars,
                    state=states["baseline"],
                    risk=risk,
                    decision_idx=i,
                    decision_bar=decision_bar,
                    meta=_forecast_to_meta_signal(baseline_forecast),
                    oos_end=oos_end,
                )

            # Ensemble pipeline: all valid forecasts -> Meta-Signal.
            if forecasts:
                meta = self._ensemble.combine(
                    forecasts=list(forecasts.values()),
                    spread_points=decision_bar.spread_points,
                    n_adapter_total=len(self._adapters),
                )
                self._step_pipeline(
                    bars=bars,
                    state=states["ensemble"],
                    risk=risk,
                    decision_idx=i,
                    decision_bar=decision_bar,
                    meta=meta,
                    oos_end=oos_end,
                )
        return states

    # -- internal ------------------------------------------------------------

    def _step_pipeline(
        self,
        *,
        bars: list[Bar],
        state: _PipelineState,
        risk: RiskManager,
        decision_idx: int,
        decision_bar: Bar,
        meta: MetaSignal,
        oos_end: int,
    ) -> None:
        if decision_idx <= state.open_until:
            # A previously-opened trade is still running through this bar;
            # the original simulate_trade already accounted for its outcome.
            return
        state.decisions += 1
        if meta.veto_reasons or meta.direction == "HOLD":
            state.veto_count += 1
            return

        atr = estimate_atr(bars, end_idx=decision_idx, window=self._cfg.atr_window)
        if atr <= 0:
            state.rejections += 1
            return
        market = self._build_market(decision_bar, atr)
        account = self._build_account(decision_bar, state.equity)
        decision = risk.evaluate(meta, account, market)
        if (
            not decision.approved
            or decision.side is None
            or decision.sl is None
            or decision.tp is None
        ):
            state.rejections += 1
            return

        entry_price = market.ask if decision.side == "BUY" else market.bid
        fill = simulate_trade(
            bars,
            side=decision.side,
            volume=decision.volume,
            entry_idx=decision_idx,
            entry_price=entry_price,
            sl=decision.sl,
            tp=decision.tp,
            oos_end_idx=oos_end,
        )
        gross_price_pnl = fill.gross_pnl_price
        gross = gross_price_pnl * self._cfg.cost_model.contract_size * fill.volume
        cost = self._cfg.cost_model.total_cost(
            side=fill.side, volume=fill.volume, n_nights=fill.nights_held
        )
        net = gross - cost
        state.equity += net
        state.open_until = fill.close_idx
        state.trades.append(
            TradeRecord(
                pipeline=state.name,
                fill=fill,
                gross_price_pnl=gross_price_pnl,
                cost=cost,
                net_pnl=net,
                contract_size=self._cfg.cost_model.contract_size,
                decision_idx=decision_idx,
                decision_time=decision_bar.open_time.isoformat(),
                confidence=meta.confidence,
                agreement=meta.agreement,
                final_score=meta.final_score,
            )
        )

    def _build_market(self, bar: Bar, atr: float) -> MarketSnapshot:
        cm = self._cfg.cost_model
        # Half-spread around the close so BUY pays ask and SELL receives bid,
        # matching how the cost model already accounts for the round-trip.
        half_spread_price = (bar.spread_points / 2.0) * cm.point_size
        bid = bar.close - half_spread_price
        ask = bar.close + half_spread_price
        return MarketSnapshot(
            symbol=self._cfg.symbol,
            bid=bid,
            ask=ask,
            spread_points=bar.spread_points,
            point_size=cm.point_size,
            contract_size=cm.contract_size,
            volume_min=0.01,
            volume_max=100.0,
            volume_step=0.01,
            stop_level_points=0,
            atr=atr,
            margin_per_lot=ask * cm.contract_size * 0.01,  # 1% leverage proxy
            timestamp=bar.open_time,
        )

    def _build_account(self, bar: Bar, equity: float) -> AccountSnapshot:
        return AccountSnapshot(
            balance=equity,
            equity=equity,
            free_margin=equity,
            margin_used=0.0,
            open_positions=0,
            open_positions_for_symbol=0,
            consecutive_losses=0,
            trades_today=0,
            daily_pnl_pct=0.0,
            drawdown_pct=0.0,
            timestamp=bar.open_time,
        )


def _forecast_to_meta_signal(forecast: Forecast) -> MetaSignal:
    """Wrap a single Forecast in a MetaSignal so the Risk gate can consume it.

    Used for the baseline-only pipeline so it traverses the same Risk
    Decision logic as the ensemble pipeline -- a fair apples-to-apples
    comparison.
    """
    return MetaSignal(
        direction=forecast.direction,
        final_score=forecast.score,
        raw_score=forecast.raw_score,
        agreement=1.0,  # single-model => max agreement by definition
        confidence=forecast.confidence,
        cost_penalty=0.0,
        uncertainty_penalty=forecast.uncertainty,
        event_penalty=0.0,
        veto_reasons=[],
        reason=f"baseline-only direction={forecast.direction}",
        components={forecast.model_name: forecast},
        timestamp=forecast.timestamp,
    )


class _StubKillSwitch:
    """In-memory kill switch that always reports disengaged.

    The real :class:`KillSwitch` reads ``kill_switch_file``; for offline
    backtests we never want side-effects on the host filesystem.
    """

    def is_engaged(self) -> bool:
        return False


_ = (datetime, timedelta, ExecutionConfig, KillSwitch)  # silence unused-import lint
