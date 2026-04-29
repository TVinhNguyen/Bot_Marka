# 12. Configuration spec

## 12.1 Triết lý

```text
- Config-driven: model/risk/symbol đổi qua YAML, không sửa code
- Env-aware: dev / dry_run / demo / live
- Secrets KHÔNG nằm trong YAML, dùng env var (.env hoặc vault)
- Versioned: mọi thay đổi config commit vào git
- Validated: pydantic / dataclass schema check tại startup
```

---

## 12.2 Cấu trúc thư mục config

```text
config/
  config.yaml             - main, có ${VAR}
  symbols.yaml            - danh sách symbol + timeframe
  model_weights.yaml      - weight ensemble
  risk.yaml               - risk limits
  brokers/
    broker_a.yaml
    broker_b.yaml
  envs/
    dev.yaml
    demo.yaml
    live.yaml
```

Load order: `config.yaml` < `envs/<ENV>.yaml` < CLI override.

---

## 12.3 config.yaml mẫu

```yaml
environment:
  mode: ${ENV:dry_run}           # dry_run | demo | live
  timezone: "UTC"
  log_level: "INFO"

mt5:
  terminal_path: ""
  login: ${MT5_LOGIN}
  server: ${MT5_SERVER}
  password_env: "MT5_PASSWORD"
  broker_profile: "broker_a"

schedule:
  trigger: "interval"
  seconds: 60
  align_to_close_bar: true

symbols: !include symbols.yaml

data:
  bars: 600
  prediction_horizon: 8
  use_closed_bar_only: true
  cross_assets: ["DXY", "VIX", "US10Y"]
  storage:
    backend: "duckdb"            # duckdb | parquet | postgres
    path: "data/bars"

models:
  timesfm:
    enabled: true
    target: "log_return"
    context_length: 512
    horizon: 8
    backend: "torch"             # torch | jax

  kronos:
    enabled: true
    input_columns: ["open","high","low","close","tick_volume"]
    context_length: 512
    horizon: 8
    checkpoint: "kronos_v1.pt"

  chronos:
    enabled: true
    mode: "probabilistic"
    context_length: 512
    horizon: 8
    covariates:
      enabled: false
      columns: ["dxy_return","vix_return","us10y_change"]

  fingpt:
    enabled: true
    use_rag: true
    max_news_age_hours: 24
    sentiment_weight_decay_hours: 12
    embedder: "sentence-transformers/all-mpnet-base-v2"
    vector_db:
      backend: "milvus"
      uri: ${MILVUS_URI}
      collection: "ai_mt5_news"

  baseline:
    enabled: true
    kind: "lightgbm"
    model_path: "models/baseline_lgbm.pkl"

ensemble: !include model_weights.yaml

cost_model:
  slippage_buffer_points: 5
  min_edge_to_cost_ratio: 1.5

risk: !include risk.yaml

execution:
  dry_run: ${DRY_RUN:true}
  deviation_points: 20
  magic: 26042901
  order_comment: "ai-mt5-mm"
  reconcile_on_start: true

monitoring:
  signals_csv: "logs/signals.csv"
  trades_csv: "logs/trades.csv"
  errors_log: "logs/errors.log"
  prometheus_port: 9090
  alerts:
    telegram:
      enabled: true
      token_env: "TELEGRAM_BOT_TOKEN"
      chat_id_env: "TELEGRAM_CHAT_ID"
    email:
      enabled: false

agents:
  enabled: false                 # MVP dùng pipeline thẳng
  framework: "langgraph"
```

---

## 12.4 symbols.yaml mẫu

```yaml
symbols:
  - symbol: "EURUSD"
    timeframe: "M15"
    enabled: true
    spread_max_points: 25
    session_filter:
      allow_sessions: ["london","ny"]
    notes: "primary symbol cho MVP"

  - symbol: "XAUUSD"
    timeframe: "M15"
    enabled: false
    spread_max_points: 60

  - symbol: "NAS100"
    timeframe: "M15"
    enabled: false
    spread_max_points: 200
```

---

## 12.5 model_weights.yaml mẫu

```yaml
ensemble:
  weights:
    kronos:    0.35
    timesfm:   0.25
    chronos:   0.20
    sentiment: 0.15
    baseline:  0.05

  buy_threshold:    0.25
  sell_threshold:   0.25
  min_agreement:    0.60
  min_models:       3
  max_uncertainty:  0.75
  max_event_risk:   0.80

  uncertainty_weight: 0.30
  event_weight:       0.40
  min_edge_to_cost_ratio: 1.5

  regime_overrides:
    trend:        { kronos_mult: 1.10, timesfm_mult: 1.05 }
    mean_revert:  { chronos_mult: 1.10 }
    chop:         { disable_trade: true }
    high_vol:     { threshold_mult: 1.5 }
```

---

## 12.6 risk.yaml mẫu

```yaml
risk:
  base_risk_per_trade: 0.002
  max_risk_per_trade:  0.005
  min_risk_per_trade:  0.0005
  max_daily_loss:      0.02
  max_total_drawdown:  0.08
  max_positions_per_symbol: 1
  max_total_positions:      3
  max_trades_per_day:       5
  max_consecutive_losses:   3

  sl_atr_min: 1.2
  sl_atr_max: 2.5
  tp_atr:     2.0
  rr_min:     1.0
  margin_safety: 0.8

  spread_max_points:
    EURUSD: 25
    XAUUSD: 60
    NAS100: 200

  news_window_minutes:
    high:   [-30, +30]
    medium: [-10, +15]
    low:    [0, 0]

  kill_switch:
    enabled: true
    drawdown_pct: 0.08
    manual_file: "/var/run/ai-mt5/STOP"
    close_positions: false

  soft_breakers:
    after_consecutive_losses_3:
      action: "halve_risk"
    after_consecutive_losses_5:
      action: "stop_until_next_day"
    after_daily_loss_1pct:
      action: "halve_risk"
    weekly_loss_5pct:
      action: "stop_until_review"
```

---

## 12.7 brokers/broker_a.yaml mẫu

```yaml
broker:
  name: "BrokerA Demo"
  spread_points:
    EURUSD: 12
    XAUUSD: 35
    NAS100: 150
  commission_per_lot:
    EURUSD: 7.0
    XAUUSD: 0.0
    NAS100: 0.0
  swap:
    EURUSD: { long: -2.5, short: -1.2 }
    XAUUSD: { long: -8.0, short: -3.5 }
  filling_modes:
    EURUSD: ["IOC","FOK"]
  trade_stops_level_points:
    EURUSD: 0
    XAUUSD: 50
```

---

## 12.8 .env.example

```bash
# MT5
MT5_LOGIN=12345678
MT5_SERVER=BrokerA-Demo
MT5_PASSWORD=replace-me

# RAG / vector DB
MILVUS_URI=grpc://localhost:19530

# News / API
NEWSAPI_KEY=
OPENAI_API_KEY=

# Alerts
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# Runtime
ENV=dry_run
DRY_RUN=true
```

`.env` luôn `git-ignored`. Production dùng secret manager (Vault, AWS Secrets, GCP Secret).

---

## 12.9 Schema validation

Tại startup, load config qua pydantic:

```python
class RiskConfig(BaseModel):
    base_risk_per_trade: float = Field(gt=0, lt=0.01)
    max_risk_per_trade:  float = Field(gt=0, lt=0.02)
    max_daily_loss:      float = Field(gt=0, lt=0.10)
    ...

class AppConfig(BaseModel):
    environment: EnvConfig
    mt5: MT5Config
    risk: RiskConfig
    ensemble: EnsembleConfig
    execution: ExecutionConfig
    ...

cfg = AppConfig.model_validate(yaml_dict)
```

Nếu config invalid -> fail fast, không start service.

---

## 12.10 Hot reload

```text
- KHÔNG cho phép hot reload risk.yaml trong live mode
- Reload chỉ thông qua restart có audit
- Thay đổi config phải:
    1. PR + review
    2. Diff được log vào audit
    3. Trước khi reload trên live: snapshot equity và position
```

Risk-related changes phải được approve bởi 2 người (4-eyes rule) trong production.

---

## 12.11 Config diff & audit

Khi reload:

```text
- log JSON: {"event": "config_change", "diff": {...}, "actor": "...", "ts": "..."}
- alert Telegram nếu thay đổi `risk.*` hoặc `execution.dry_run`
- giữ history N versions trong git + DB
```
