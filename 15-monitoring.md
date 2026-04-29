# 15. Monitoring, logging, alerting

## 15.1 Triết lý

```text
- Mọi quyết định trade phải có audit trail đầy đủ
- Log structured (JSON) -> dễ query, filter
- Metrics realtime cho dashboard
- Alert chia mức nghiêm trọng, không spam
- Logs là tài sản quan trọng nhất khi xảy ra incident
```

---

## 15.2 Logging contract

### 15.2.1 Format

JSONL, một dòng = một event:

```json
{"ts":"2026-04-29T14:00:00Z","level":"INFO","event":"forecast","model":"kronos","symbol":"EURUSD","timeframe":"M15","horizon":8,"score":0.55,"direction":"BUY","confidence":0.7,"reason":"k-line bullish","trace_id":"abc..."}
```

### 15.2.2 Trace ID

Mỗi tick có `trace_id` xuyên suốt:

```text
forecast (5 records) -> ensemble (1) -> risk (1) -> order_check (1) -> order_send (1)
```

Truy vết một trade chỉ cần `grep trace_id`.

### 15.2.3 File rotation

```text
logs/runner.log     -> daily rotation, giữ 30 ngày
logs/errors.log     -> daily rotation, giữ 90 ngày
logs/signals.csv    -> append-only, không xóa
logs/trades.csv     -> append-only, không xóa
```

Audit logs (signals, trades) **không** rotate-and-delete; chỉ archive.

---

## 15.3 Event taxonomy

| Event | Khi nào | Level |
|---|---|---|
| `tick.start` | Mỗi tick bắt đầu | DEBUG |
| `data.fetch_ok` | Lấy data thành công | DEBUG |
| `data.stale` | Data quá cũ | WARN |
| `forecast.ok` | Adapter trả forecast | INFO |
| `forecast.fail` | Adapter exception | ERROR |
| `ensemble.result` | Ensemble ra signal | INFO |
| `ensemble.veto` | Hit hard veto rule | WARN |
| `risk.approved` | Risk approve | INFO |
| `risk.rejected` | Risk reject | WARN |
| `order.check_ok` | order_check pass | INFO |
| `order.check_fail` | order_check fail | ERROR |
| `order.send_ok` | order_send done | INFO |
| `order.send_fail` | order_send fail | CRITICAL |
| `kill_switch.triggered` | Kill switch on | CRITICAL |
| `config.changed` | Config reload | WARN |
| `mt5.disconnected` | Mất kết nối | CRITICAL |
| `health.ok/health.fail` | Heartbeat | DEBUG/CRITICAL |

---

## 15.4 Metrics (Prometheus / CSV)

### 15.4.1 Counter
```text
trades_attempted_total{symbol,side}
trades_filled_total{symbol,side}
trades_rejected_total{reason}
forecasts_total{model,direction}
errors_total{type,module}
kill_switch_triggered_total{trigger}
```

### 15.4.2 Gauge
```text
account_equity
account_balance
account_drawdown_pct
open_positions{symbol}
spread_points{symbol}
last_tick_age_seconds
```

### 15.4.3 Histogram
```text
inference_latency_seconds{model}
order_send_latency_seconds
slippage_points{symbol}
ensemble_final_score{symbol}
```

---

## 15.5 Dashboard

### 15.5.1 MVP — Streamlit

```text
Pages:
  - Overview: equity curve, today PnL, open positions, kill switch state
  - Signals: signals timeline với drill-down vào forecasts
  - Trades: trade list, win/loss, slippage
  - Models: forecast accuracy per model, latency, fail rate
  - Risk: drawdown, exposure, today trades, soft breakers state
  - Health: data freshness, MT5 connection, errors per module
```

### 15.5.2 Production — Grafana

```text
- Datasource: Prometheus + Postgres
- Dashboards versioned trong repo (provisioning JSON)
- Variables: symbol, timeframe, time range
- Alerts cấu hình trong Grafana hoặc Alertmanager
```

---

## 15.6 Alerting

### 15.6.1 Mức nghiêm trọng

| Mức | Trigger | Kênh | SLA |
|---|---|---|---|
| INFO | trade filled, daily summary | Telegram | best-effort |
| WARN | risk reject pattern, data stale | Telegram | <= 5 min |
| ERROR | adapter fail, order_check fail | Telegram + email | <= 1 min |
| CRITICAL | order_send fail, MT5 disconnect, kill switch, drawdown breach | Telegram + email + (PagerDuty production) | <= 30s |

### 15.6.2 Anti-spam

```text
- Dedupe theo (alert_key, 10 phút)
- Rate limit max 10 alerts / phút
- Daily summary thay vì alert mỗi tick
- Critical luôn gửi (không dedupe)
```

### 15.6.3 Telegram bot

```python
def send_telegram(level, message, dedupe_key=None):
    if should_dedupe(dedupe_key):
        return
    requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": format_msg(level, message), "parse_mode": "Markdown"},
        timeout=5
    )
```

---

## 15.7 Audit trail

Mỗi trade có audit record bất biến (append-only):

```json
{
  "audit_id": "f3c1...e9",
  "trace_id": "abc...",
  "ts": "2026-04-29T14:00:00Z",
  "symbol": "EURUSD",
  "forecasts": [...],
  "ensemble": {...},
  "risk_decision": {...},
  "order_request": {...},
  "order_check": {...},
  "order_send": {...},
  "config_snapshot_hash": "...",
  "code_commit": "a1b2c3d"
}
```

Lưu trong DB và backup ra S3/Glacier nếu yêu cầu compliance.

---

## 15.8 Healthcheck

Endpoint `/health` trả về:

```json
{
  "ok": true,
  "mt5_connected": true,
  "last_tick_age_seconds": 3,
  "open_positions": 1,
  "kill_switch_active": false,
  "data_freshness": {
    "EURUSD_M15": 12,
    "news": 240
  },
  "model_status": {
    "kronos": "ok",
    "timesfm": "ok",
    "chronos": "ok",
    "fingpt": "degraded"
  }
}
```

Probe mỗi 30s. 3 lần fail liên tiếp -> CRITICAL alert.

---

## 15.9 Daily/weekly reports

### Daily (sau khi đóng phiên)
```text
- Số trade, win rate, PnL ngày
- Drawdown, exposure
- Reject reasons top 5
- Adapter fail count
- So sánh với ngày liền kề
```

### Weekly
```text
- Sharpe rolling 4 tuần
- Equity curve weekly
- Per-symbol PnL
- Slippage thực tế vs buffer
- Top reasons reject
- So với backtest cùng giai đoạn
```

Format: Markdown hoặc HTML, gửi qua email/Telegram.

---

## 15.10 Drift detection

Theo dõi:

```text
- Forecast accuracy theo tuần (rolling)
- Calibration: Brier score per model
- Distribution shift: KS-test cho score distribution
- Slippage drift
- Spread drift (broker thay đổi điều kiện)
- Win rate drift
```

Drift trigger:
```text
- Sharpe live giảm > 50% so với backtest -> WARN
- Drawdown > 0.5x max_drawdown limit -> WARN
- Forecast accuracy < random baseline 2 tuần liên tiếp -> CRITICAL, dừng trade
```

---

## 15.11 Incident response

Khi CRITICAL alert:

```text
1. Operator nhận alert -> nhìn dashboard
2. Nếu cần: trigger kill switch (manual file)
3. Capture: latest logs, DB state, MT5 state
4. Mở incident ticket
5. Sau khi xử lý: postmortem trong 48h
6. Cập nhật runbook
```

Runbook nên có sẵn cho các incident phổ biến:
- MT5 disconnect kéo dài
- Adapter raise exception liên tục
- order_send timeout
- DB lock / disk full
- News pipeline down

---

## 15.12 Data retention

| Loại | Retention |
|---|---|
| Bars (tick) | 12 tháng full, sau đó downsample |
| Bars (M1+) | vĩnh viễn |
| Forecasts | 24 tháng |
| Signals | 24 tháng |
| Trades | vĩnh viễn |
| Audit logs | vĩnh viễn (compliance) |
| Runner logs | 90 ngày |
| News raw | 12 tháng |
| Embeddings | có thể rebuild, 12 tháng cũng đủ |
