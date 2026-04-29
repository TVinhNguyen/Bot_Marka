# 02. Kiến trúc tổng thể

## 2.1 Sơ đồ tầng (high-level)

```text
┌────────────────────────────────────────────────────────────────┐
│                        DATA SOURCES                            │
├────────────────────────────────────────────────────────────────┤
│ MT5 (bars, ticks, spread, account)                             │
│ OpenBB / Yahoo / Polygon / Binance / IBKR (tùy thị trường)     │
│ News feeds (RSS, API), macro calendar, filings, social         │
└────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌────────────────────────────────────────────────────────────────┐
│                        DATA LAYER                              │
├────────────────────────────────────────────────────────────────┤
│ Time-series store: Parquet / DuckDB / Postgres+TimescaleDB     │
│ Document store: SQLite/Postgres (raw news, filings)            │
│ Vector DB: Milvus / Zilliz (chỉ cho RAG/embeddings)            │
│ Prediction store: SQLite/Postgres (forecast logs)              │
└────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌────────────────────────────────────────────────────────────────┐
│                        MODEL LAYER                             │
├────────────────────────────────────────────────────────────────┤
│ TimesFMAdapter   -> close/log-return/volatility forecast       │
│ KronosAdapter    -> OHLCV/K-line forecast (model chính)        │
│ ChronosAdapter   -> probabilistic + multivariate forecast      │
│ FinGPTAdapter    -> sentiment / event_risk / news summary      │
│ BaselineAdapter  -> SMA/ATR/LightGBM control                   │
└────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌────────────────────────────────────────────────────────────────┐
│                    META-SIGNAL ENGINE                          │
├────────────────────────────────────────────────────────────────┤
│ Normalize từng score về [-1, +1]                               │
│ Tính agreement / disagreement                                  │
│ Trừ transaction cost (spread + commission + slippage)          │
│ Kiểm tra uncertainty / volatility regime / event_risk          │
│ Output: BUY / SELL / HOLD + confidence + reason                │
└────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌────────────────────────────────────────────────────────────────┐
│                       RISK MANAGER                             │
├────────────────────────────────────────────────────────────────┤
│ max_risk_per_trade, max_daily_loss, max_drawdown               │
│ max_open_positions, max_trades_per_day                         │
│ SL/TP bắt buộc, news no-trade window                           │
│ Kill switch (manual + automatic)                               │
└────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌────────────────────────────────────────────────────────────────┐
│                       MT5 EXECUTOR                             │
├────────────────────────────────────────────────────────────────┤
│ Option A: Python MetaTrader5: order_check + order_send         │
│ Option B: MQL5 EA + Python AI server (REST/ZMQ/file bridge)    │
└────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌────────────────────────────────────────────────────────────────┐
│                    OBSERVABILITY LAYER                         │
├────────────────────────────────────────────────────────────────┤
│ structured logs (JSONL)                                        │
│ signals.csv, trades.csv, errors.log                            │
│ Grafana / Streamlit dashboard                                  │
│ Alert: Telegram / email / PagerDuty                            │
└────────────────────────────────────────────────────────────────┘
```

---

## 2.2 Luồng quyết định (decision flow)

```text
1. Scheduler tick (mỗi N giây hoặc trên close-bar event)
2. Data loader -> đọc nến đã đóng từ MT5 + news lookback window
3. Feature builder -> log-return, ATR, volatility, normalize OHLCV
4. Mỗi adapter chạy predict() song song -> ModelForecast
5. Ensemble engine -> raw_score, agreement, cost-adjusted final_score
6. Pre-risk filter -> threshold, agreement, event_risk
7. Risk manager -> sizing, SL/TP, kiểm tra equity/drawdown/exposure
8. MT5 order_check -> validate request với broker
9. Nếu dry_run -> log; nếu live -> order_send
10. Persist forecast + signal + result vào prediction store
11. Push metrics vào dashboard, alert nếu vi phạm rule
```

---

## 2.3 Component boundaries

| Component | Owns | Không được làm |
|---|---|---|
| Data layer | I/O, schema, cache | Không tạo signal |
| Model adapter | Inference + normalization | Không gọi executor, không biết về account |
| Ensemble | Combine, filter, threshold | Không chọn lot, không gọi MT5 |
| Risk manager | Sizing, hard limits, kill switch | Không sửa forecast |
| Executor | order_check, order_send | Không tự tăng/giảm lot ngoài input |
| Agent layer | Orchestration, audit, report | Không gửi order trực tiếp |

Boundary này là **bất di bất dịch**. Vi phạm ranh giới = bug nghiêm trọng.

---

## 2.4 Deployment topology

### MVP topology (single machine)

```text
┌──────────────────────────────────────────┐
│ VPS / Workstation (Windows hoặc Linux)   │
│ ┌──────────────────────────────────────┐ │
│ │ MT5 Terminal (Windows native)        │ │
│ └──────────────────────────────────────┘ │
│ ┌──────────────────────────────────────┐ │
│ │ Python service (cron / systemd)      │ │
│ │   - data collector                   │ │
│ │   - model inference                  │ │
│ │   - ensemble + risk + executor       │ │
│ └──────────────────────────────────────┘ │
│ ┌──────────────────────────────────────┐ │
│ │ SQLite/Postgres + Parquet local      │ │
│ └──────────────────────────────────────┘ │
└──────────────────────────────────────────┘
```

### Production topology (sau giai đoạn 9)

```text
┌──── MT5 Host (Windows VPS) ──────┐    ┌──── AI Server (GPU) ─────┐
│ MT5 Terminal                     │    │ Model inference service  │
│ MQL5 EA executor                 │◄──►│ FastAPI / ZeroMQ         │
│ Local logger                     │    │ TimesFM / Kronos / FinGPT│
└──────────────────────────────────┘    └──────────────────────────┘
            │                                       │
            └──────► Postgres / TimescaleDB ◄───────┘
            └──────► Grafana + Alertmanager ◄───────┘
```

---

## 2.5 Tham chiếu chi tiết

- Model layer: xem [04-models.md](04-models.md)
- Data layer: xem [05-data-pipeline.md](05-data-pipeline.md)
- Ensemble: xem [06-meta-signal.md](06-meta-signal.md)
- Risk: xem [07-risk-management.md](07-risk-management.md)
- MT5 layer: xem [08-mt5-execution.md](08-mt5-execution.md)
- Agent: xem [09-agents.md](09-agents.md)
- Project layout: xem [11-project-structure.md](11-project-structure.md)
