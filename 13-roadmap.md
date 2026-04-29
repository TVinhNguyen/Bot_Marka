# 13. Roadmap theo giai đoạn

## 13.1 Tóm tắt 9 giai đoạn

| Giai đoạn | Tên | Mục tiêu chính | Trạng thái | DoD |
|---|---|---|---|---|
| 1 | MT5 skeleton | Connector, dry_run order_check | ⬜ | order_check pass, không order_send |
| 2 | Baseline + logging | Baseline strategy, logging, storage | ⬜ | Pipeline e2e với baseline |
| 3 | TimesFM offline | Forecast trên lịch sử | ⬜ | Forecast lưu vào predictions |
| 4 | Kronos offline | OHLCV forecast | ⬜ | Direction accuracy + edge sau cost |
| 5 | Chronos offline | Probabilistic forecast | ⬜ | So sánh với TimesFM/Kronos |
| 6 | FinGPT/RAG offline | Sentiment + event_risk | ⬜ | Sentiment correlation với biến động |
| 7 | Ensemble backtest | Tune weight, walk-forward | ⬜ | OOS thắng baseline sau cost |
| 8 | Paper / demo | Live shadow + demo trading | ⬜ | 2-4 tuần demo không lỗi nghiêm trọng |
| 9 | Live nhỏ | Risk 0.05-0.1% / trade | ⬜ | Kill switch test pass, drawdown trong limit |

---

## 13.2 Giai đoạn 1 — MT5 skeleton (Tuần 1, ngày 1-3)

### Mục tiêu
- Kết nối MT5, đọc bars/tick/account/spread
- Tạo order request, chạy `order_check` trong dry_run
- **Không gửi lệnh thật**

### Deliverable
```text
src/mt5/connection.py
src/mt5/market_data.py
src/mt5/account.py
src/mt5/executor.py    (dry_run only)
config/config.yaml + symbols.yaml
logs/runner.log
```

### Definition of Done
- [ ] Kết nối MT5 demo thành công, reconnect được
- [ ] Lấy 600 nến closed cho EURUSD M15
- [ ] `order_check` trả `TRADE_RETCODE_DONE` cho request mẫu
- [ ] Dry-run output ghi vào `logs/`
- [ ] Test integration với demo account

---

## 13.3 Giai đoạn 2 — Baseline + logging (Tuần 1, ngày 4-7)

### Mục tiêu
Pipeline e2e với baseline (SMA/ATR), logging đầy đủ, storage tốt.

### Deliverable
```text
src/data/feature_builder.py
src/data/storage.py
src/models/baseline_adapter.py
src/signal/ensemble.py    (chỉ baseline, weight = 1.0)
src/risk/risk_manager.py
src/risk/position_sizing.py
src/monitoring/logger.py
logs/signals.csv, trades.csv, errors.log
```

### Definition of Done
- [ ] Pipeline tick chạy trên dry_run
- [ ] Baseline ra signal hợp lệ
- [ ] Risk manager reject đúng các trường hợp test
- [ ] DB lưu forecast + signal + risk decision
- [ ] Có dashboard Streamlit cơ bản (ít nhất bảng signals)

---

## 13.4 Giai đoạn 3 — TimesFM offline (Tuần 2, ngày 1-2)

### Mục tiêu
Chạy TimesFM trên dữ liệu lịch sử, lưu forecast, đánh giá độ chính xác.

### Deliverable
```text
src/models/timesfm_adapter.py
notebooks/02_timesfm_forecast.ipynb
data/predictions/timesfm/EURUSD_M15.parquet
reports/timesfm_eval.md
```

### Definition of Done
- [ ] Forecast log_return cho >= 6 tháng dữ liệu
- [ ] Direction accuracy out-of-sample > 50%
- [ ] Edge sau cost được tính, dù dương hay âm phải report rõ
- [ ] Model adapter trả `ModelForecast` đúng schema
- [ ] **KHÔNG gọi adapter trong execution loop**

---

## 13.5 Giai đoạn 4 — Kronos offline (Tuần 2, ngày 3-4)

### Mục tiêu
Kronos forecast OHLCV, đo direction probability, expected return.

### Deliverable
```text
src/models/kronos_adapter.py
notebooks/03_kronos_forecast.ipynb
data/predictions/kronos/EURUSD_M15.parquet
reports/kronos_eval.md
```

### Definition of Done
- [ ] Pin commit hash Kronos repo
- [ ] Forecast OHLC sample reasonable so với baseline naive (close = close[-1])
- [ ] Direction probability calibrated (Brier score < 0.25)
- [ ] Adapter conform schema

---

## 13.6 Giai đoạn 5 — Chronos offline (Tuần 2, ngày 5-7)

### Mục tiêu
Chronos/Chronos-2 probabilistic forecast, thử covariate.

### Deliverable
```text
src/models/chronos_adapter.py
notebooks/04_chronos_forecast.ipynb
data/cross_assets/...
reports/chronos_eval.md
```

### Definition of Done
- [ ] Forecast quantile p10/p50/p90 được lưu
- [ ] Test với và không có covariates
- [ ] Adapter conform schema

---

## 13.7 Giai đoạn 6 — FinGPT/RAG offline (Tuần 3, ngày 1-3)

### Mục tiêu
Pipeline news → embeddings → sentiment + event_risk.

### Deliverable
```text
src/data/news_loader.py
src/models/fingpt_adapter.py
data/documents/news/...
data/embeddings/milvus/
reports/fingpt_eval.md
```

### Definition of Done
- [ ] News loader pull được 30 ngày dữ liệu cho EURUSD/XAUUSD
- [ ] Embedding pipeline hoạt động, retrieve ra documents liên quan
- [ ] Sentiment score correlate >= 0.15 với realized return ngắn hạn (sanity)
- [ ] Event_risk tăng đúng quanh sự kiện CPI/NFP đã biết

---

## 13.8 Giai đoạn 7 — Ensemble backtest (Tuần 3, ngày 4-7)

### Mục tiêu
Kết hợp tất cả model, walk-forward, tune weight, so baseline.

### Deliverable
```text
src/signal/ensemble.py    (đầy đủ)
src/signal/cost_model.py
src/backtest/engine.py
src/backtest/walk_forward.py
src/backtest/metrics.py
reports/ensemble_backtest_v1.html
```

### Definition of Done
- [ ] Walk-forward >= 6 windows trên dữ liệu OOS
- [ ] Ensemble vượt baseline về Sharpe và Calmar
- [ ] Drawdown <= 8% trong OOS
- [ ] Stress tests đều pass với DD <= 2x baseline DD
- [ ] Report reproducibility (commit + lock + seed)

> Nếu DoD không đạt, **dừng**, quay lại tune model/threshold trước khi tiếp giai đoạn 8.

---

## 13.9 Giai đoạn 8 — Paper / demo (Tuần 4 trở đi, 2-4 tuần)

### Mục tiêu
Pipeline live trên demo account, dry_run=false với risk rất nhỏ.

### Deliverable
```text
runtime live trên demo
shadow log đầy đủ
report so sánh shadow vs backtest
```

### Definition of Done
- [ ] >= 2 tuần liên tục không crash silent
- [ ] Reconcile chính xác sau restart
- [ ] Slippage thực tế <= 1.2x slippage_buffer
- [ ] Spread/event window logic chạy đúng
- [ ] Telegram alert hoạt động cho mọi error stage
- [ ] Drawdown demo trong limit

---

## 13.10 Giai đoạn 9 — Live nhỏ (sau khi giai đoạn 8 pass)

### Điều kiện đầu vào (gate)
```text
[ ] Backtest OOS pass
[ ] Demo 2-4 tuần pass
[ ] Kill switch test thành công
[ ] Risk officer / quant lead duyệt
[ ] Operator nắm được quy trình stop/restart
```

### Live size khởi điểm
```text
risk_per_trade = 0.05% - 0.1%
max_daily_loss = 0.5%
max_total_drawdown = 3%
1 symbol, 1 timeframe
```

### Lộ trình tăng size
```text
- 4 tuần đầu: cố định size nhỏ
- Mỗi 4 tuần: review metrics live vs backtest
- Tăng size 2x chỉ khi: live Sharpe > 0.7 * backtest Sharpe và DD < limit
- Không tăng > 0.5% / trade trong 6 tháng đầu
```

---

## 13.11 Mốc tuần (cô đọng từ blueprint)

### Tuần 1
```text
MT5 connector, dry_run, baseline + logging, data storage
```

### Tuần 2
```text
TimesFM offline, Kronos offline, Chronos offline, eval reports
```

### Tuần 3
```text
FinGPT/RAG, ensemble engine, backtest framework, walk-forward
```

### Tuần 4
```text
Paper trading, demo trading risk nhỏ, monitoring, fix execution
```

### Sau tuần 4
```text
walk-forward tuning, multi-symbol expansion, MQL5 EA executor (Option B), live nhỏ với kill switch
```

---

## 13.12 Decision gates

Mỗi giai đoạn kết thúc bằng **gate review**:

```text
- Quant lead review report
- Backend lead review code + tests
- Risk officer review limits + audit trail
- Operator confirm vận hành được
```

Không pass gate -> không bước sang giai đoạn tiếp theo.
