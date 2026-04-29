# 11. Project structure

## 11.1 Layout

```text
ai-mt5-multimodel-bot/
├── README.md
├── pyproject.toml
├── uv.lock                       (hoặc poetry.lock)
├── .env.example
├── .gitignore
├── Dockerfile                    (cho AI server, optional)
│
├── config/
│   ├── config.yaml               (env-aware, dùng ${VAR})
│   ├── symbols.yaml
│   ├── model_weights.yaml
│   ├── risk.yaml
│   └── brokers/
│       ├── broker_a.yaml
│       └── broker_b.yaml
│
├── src/
│   ├── main.py                   (entrypoint)
│   ├── runner.py                 (scheduler loop)
│   │
│   ├── mt5/
│   │   ├── connection.py
│   │   ├── market_data.py
│   │   ├── account.py
│   │   ├── executor.py
│   │   └── reconcile.py
│   │
│   ├── data/
│   │   ├── collectors.py         (MT5 + external)
│   │   ├── storage.py            (parquet/sqlite/postgres)
│   │   ├── feature_builder.py
│   │   └── news_loader.py
│   │
│   ├── models/
│   │   ├── base.py               (ModelForecast dataclass + Adapter ABC)
│   │   ├── timesfm_adapter.py
│   │   ├── kronos_adapter.py
│   │   ├── chronos_adapter.py
│   │   ├── fingpt_adapter.py
│   │   └── baseline_adapter.py
│   │
│   ├── signal/
│   │   ├── normalizer.py
│   │   ├── ensemble.py
│   │   ├── cost_model.py
│   │   └── regime_filter.py
│   │
│   ├── risk/
│   │   ├── risk_manager.py
│   │   ├── position_sizing.py
│   │   ├── kill_switch.py
│   │   └── circuit_breakers.py
│   │
│   ├── agents/                   (optional, chỉ khi dùng LangGraph)
│   │   ├── data_agent.py
│   │   ├── news_agent.py
│   │   ├── quant_agent.py
│   │   ├── ensemble_agent.py
│   │   ├── risk_agent.py
│   │   └── audit_agent.py
│   │
│   ├── backtest/
│   │   ├── engine.py
│   │   ├── walk_forward.py
│   │   ├── cost_model.py
│   │   ├── metrics.py
│   │   └── reports.py
│   │
│   ├── monitoring/
│   │   ├── logger.py
│   │   ├── dashboard.py          (Streamlit)
│   │   ├── alerts.py             (Telegram/email)
│   │   └── healthcheck.py
│   │
│   └── utils/
│       ├── time_utils.py
│       ├── lot_math.py
│       └── config_loader.py
│
├── tests/
│   ├── unit/
│   │   ├── test_normalizer.py
│   │   ├── test_ensemble.py
│   │   ├── test_risk_manager.py
│   │   └── ...
│   ├── integration/
│   │   ├── test_mt5_connection.py
│   │   └── test_pipeline_e2e.py
│   ├── property/
│   │   └── test_position_sizing_props.py
│   └── fixtures/
│       └── ...
│
├── data/
│   ├── bars/
│   ├── ticks/
│   ├── documents/
│   ├── embeddings/
│   └── predictions/
│
├── logs/
│   ├── signals.csv
│   ├── trades.csv
│   ├── runner.log
│   └── errors.log
│
├── reports/
│   ├── backtest_2026-04-29.html
│   └── ...
│
├── notebooks/
│   ├── 01_fetch_mt5_data.ipynb
│   ├── 02_timesfm_forecast.ipynb
│   ├── 03_kronos_forecast.ipynb
│   ├── 04_chronos_forecast.ipynb
│   ├── 05_fingpt_sentiment.ipynb
│   ├── 06_ensemble_explore.ipynb
│   └── 07_walk_forward.ipynb
│
└── scripts/
    ├── backfill_bars.py
    ├── retrain_baseline.py
    ├── kill_switch_set.sh
    ├── kill_switch_clear.sh
    └── reconcile.py
```

---

## 11.2 Module boundaries

```text
mt5/        <- chỉ I/O với terminal
data/       <- chỉ I/O với storage
models/     <- chỉ inference, không gọi mt5/data trực tiếp (nhận df)
signal/     <- pure logic, không I/O
risk/       <- pure logic, đọc account snapshot
agents/     <- orchestration only, không trực tiếp gọi MT5 send
backtest/   <- offline only, không import mt5/executor live
monitoring/ <- side effect (log, alert)
```

Quy tắc import:

```text
- signal/risk KHÔNG được import từ mt5/
- models KHÔNG được import từ signal/risk
- agents có thể import từ tất cả nhưng KHÔNG order_send
- main.py / runner.py là chỗ duy nhất ráp executor
```

---

## 11.3 Interface contract

### 11.3.1 ModelForecast (xem [04-models.md](04-models.md))

```python
@dataclass
class ModelForecast:
    model_name: str
    direction: str
    expected_return: float
    uncertainty: float
    raw_score: float
    score: float
    confidence: float
    horizon: int
    reason: str
    metadata: dict
```

### 11.3.2 EnsembleResult (xem [06-meta-signal.md](06-meta-signal.md))

```python
@dataclass
class EnsembleResult:
    direction: str
    final_score: float
    raw_score: float
    agreement: float
    confidence: float
    cost_penalty: float
    uncertainty_penalty: float
    event_penalty: float
    veto_reasons: list[str]
    reason: str
    components: dict[str, ModelForecast]
    timestamp: datetime
```

### 11.3.3 RiskDecision (xem [07-risk-management.md](07-risk-management.md))

```python
@dataclass
class RiskDecision:
    approved: bool
    side: str | None
    volume: float
    sl: float | None
    tp: float | None
    magic: int
    comment: str
    reason: str
    rejected_by: list[str]
```

---

## 11.4 main.py skeleton

```python
def main():
    cfg = load_config()
    setup_logging(cfg)
    mt5_conn = init_mt5(cfg)
    storage  = init_storage(cfg)
    adapters = build_adapters(cfg)
    executor = Executor(mt5_conn, cfg)

    scheduler = Scheduler(cfg)
    scheduler.add_job(
        runner.tick,
        args=(adapters, executor, storage, cfg),
        trigger=cfg.schedule.trigger,
    )
    scheduler.run()
```

---

## 11.5 runner.py skeleton

```python
def tick(adapters, executor, storage, cfg):
    for sym_cfg in cfg.symbols:
        if not sym_cfg.enabled:
            continue
        try:
            run_one_symbol(sym_cfg, adapters, executor, storage, cfg)
        except Exception as e:
            log.exception("tick_failed", symbol=sym_cfg.symbol)
            alerts.notify(f"Tick failed: {sym_cfg.symbol}: {e}")

def run_one_symbol(sym_cfg, adapters, executor, storage, cfg):
    df       = data.load_closed_bars(sym_cfg.symbol, sym_cfg.timeframe, cfg.data.bars)
    news_ctx = news.retrieve(sym_cfg.symbol, lookback_h=24)

    forecasts = [a.predict(df, news_ctx=news_ctx) for a in adapters]
    ensemble  = ensemble_engine.combine(forecasts, market_ctx(df, sym_cfg), cfg.ensemble)

    storage.save_forecasts(forecasts, ensemble)

    if ensemble.direction == "HOLD":
        return

    risk_dec = risk_manager.evaluate(ensemble, account_info(), market_ctx(df, sym_cfg), cfg.risk)
    storage.save_risk_decision(risk_dec)

    if not risk_dec.approved:
        return

    result = executor.submit(risk_dec, dry_run=cfg.execution.dry_run)
    storage.save_trade_attempt(risk_dec, result)
```

---

## 11.6 Naming conventions

```text
- snake_case cho function/variable
- PascalCase cho dataclass/class
- module name = chức năng, không phải kỹ thuật (vd: risk_manager.py không phải utils.py)
- không viết tắt khó hiểu (vd: dùng `risk_decision` không `rd`)
```

---

## 11.7 Khi nào tách module

```text
- Một file > 500 dòng -> tách
- Một class > 7 method public -> review tách
- Logic test lặp lại 3 lần -> trích helper
- Dùng cho cả live và backtest -> tách core ra module độc lập (signal/, risk/)
```

---

## 11.8 Mapping module ↔ tài liệu

| Module | Tham chiếu |
|---|---|
| `mt5/` | [08-mt5-execution.md](08-mt5-execution.md) |
| `data/` | [05-data-pipeline.md](05-data-pipeline.md) |
| `models/` | [04-models.md](04-models.md) |
| `signal/` | [06-meta-signal.md](06-meta-signal.md) |
| `risk/` | [07-risk-management.md](07-risk-management.md) |
| `agents/` | [09-agents.md](09-agents.md) |
| `backtest/` | [10-backtesting.md](10-backtesting.md) |
| `monitoring/` | [15-monitoring.md](15-monitoring.md) |
