# AI MT5 Multi-Model Trading

This context describes an auditable MetaTrader 5 trading system where model forecasts are combined into signals, filtered by hard risk gates, and only then passed to an executor. The language here keeps research, risk, execution, and operations separate.

## Language

### Decision Pipeline

**Forecast**:
A model-specific prediction about future market direction, return, uncertainty, or event risk.
_Avoid_: Trade decision, order signal

**Model Adapter**:
A boundary that converts one forecasting model's inputs and outputs into the shared forecast contract.
_Avoid_: Strategy, trader

**Baseline**:
A simple control strategy used to prove whether the AI ensemble adds value after costs.
_Avoid_: Fallback strategy, production strategy

**Meta-Signal**:
The cost-aware ensemble output that chooses BUY, SELL, or HOLD before risk sizing.
_Avoid_: Order, execution request

**Ensemble**:
The deterministic component that combines forecasts, agreement, penalties, and vetoes into a meta-signal.
_Avoid_: Agent, risk manager

**Risk Decision**:
The risk manager's approval or rejection of a meta-signal, including size, SL, TP, and rejection reasons.
_Avoid_: Forecast, signal

**Executor**:
The deterministic component that validates and submits broker order requests after risk approval.
_Avoid_: Agent, model

**Audit Trail**:
The append-only record of forecasts, meta-signals, risk decisions, order checks, execution results, config, and code version.
_Avoid_: Log only

### Trading And Market Data

**Closed Bar**:
A completed OHLCV candle that is safe to use for feature generation and forecasting.
_Avoid_: Current candle, running bar

**Running Bar**:
An unfinished OHLCV candle that must not be used as forecast input.
_Avoid_: Latest bar

**Symbol-Timeframe**:
The pair of a traded instrument and bar interval, such as EURUSD M15.
_Avoid_: Market pair, ticker interval

**Spread**:
The broker's bid/ask cost at a decision point.
_Avoid_: Fee

**Slippage Buffer**:
The assumed adverse fill movement used in cost and execution checks.
_Avoid_: Safety margin

**Event Risk**:
The risk from news or macro events that can reduce size or block a trade.
_Avoid_: Sentiment

**Out-of-Sample Window**:
A time period not used for fitting or tuning and used to judge strategy quality.
_Avoid_: Test set when time ordering is unclear

**Walk-Forward Backtest**:
A time-series validation process that repeatedly tunes on earlier windows and evaluates on later out-of-sample windows.
_Avoid_: Random split, static backtest

### Operations

**Dry Run**:
A mode that runs the pipeline and broker order checks without sending orders.
_Avoid_: Paper trading

**Shadow Mode**:
A live-data mode that records signals and outcomes without placing trades.
_Avoid_: Demo trading

**Demo Trading**:
Trading on a broker demo account with order_send enabled but no real-money exposure.
_Avoid_: Shadow mode

**Small Live**:
The first real-money mode with one symbol-timeframe and sharply reduced risk limits.
_Avoid_: Full production

**Kill Switch**:
A manual or automatic halt that rejects new trade decisions until explicitly cleared.
_Avoid_: Pause flag

**Reconciliation**:
The startup and post-timeout comparison between broker positions and local trade records.
_Avoid_: Sync only

### Agents

**Agent Layer**:
Optional orchestration and explanation around deterministic modules.
_Avoid_: Trading engine

**Tool Allowlist**:
The explicit set of tools an agent may call.
_Avoid_: Permissions in general

**Audit Narration**:
Human-readable explanation generated from deterministic decision fields.
_Avoid_: Reasoning source

## Relationships

- A **Model Adapter** produces one **Forecast** per model run.
- The **Ensemble** combines one or more **Forecasts** into one **Meta-Signal**.
- A **Meta-Signal** may become one **Risk Decision**.
- A rejected **Risk Decision** produces no broker order request.
- An approved **Risk Decision** may be passed to the **Executor**.
- The **Executor** runs broker validation before any order submission.
- Every **Forecast**, **Meta-Signal**, **Risk Decision**, and executor result belongs to one **Audit Trail**.
- **Dry Run**, **Shadow Mode**, **Demo Trading**, and **Small Live** are distinct promotion stages.
- The **Agent Layer** may narrate or orchestrate deterministic modules but must not submit orders or mutate risk config.

## Example dialogue

> **Dev:** "If Kronos predicts BUY, should the executor place a BUY order?"
> **Domain expert:** "No. Kronos only produces a **Forecast**. The **Ensemble** must produce a **Meta-Signal**, the risk manager must approve a **Risk Decision**, and only then can the **Executor** validate the broker request."

> **Dev:** "Can we use the latest MT5 candle because it has the newest price?"
> **Domain expert:** "No. That is a **Running Bar**. Forecasting and backtests must use **Closed Bars** only."

## Flagged ambiguities

- "Signal" is overloaded in trading systems. Resolved: use **Meta-Signal** for the ensemble's BUY/SELL/HOLD output and **Risk Decision** for the risk manager's approve/reject output.
- "Paper trading" is overloaded. Resolved: use **Shadow Mode** for no-order live-data capture and **Demo Trading** for broker demo account orders.
- "Agent" can imply autonomy. Resolved: the **Agent Layer** is orchestration and narration only; deterministic modules remain the source of truth.

