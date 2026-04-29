# 01. Tổng quan dự án

## 1.1 Mục tiêu

Xây dựng một hệ thống trading tự động trên MetaTrader 5 sử dụng **multi-model ensemble AI** để tạo signal, kết hợp với **risk engine rule-cứng** để quản trị rủi ro và **MT5 executor** để đặt lệnh.

Hệ thống không phải:
- "Một bot AI duy nhất ra quyết định trade"
- "Một LLM tự đặt lệnh"

Hệ thống là:
- **Multi-model forecasting** với mỗi model giữ một vai trò chuyên biệt
- **Hard risk gates** không thể bị model bypass
- **Auditable pipeline** mỗi quyết định đều có lý do truy vết được

---

## 1.2 Scope

### In-scope (MVP)

```text
- Kết nối MT5 (Python MetaTrader5 package)
- Lấy bars/ticks/spread/account info
- Adapter cho TimesFM, Kronos, Chronos, FinGPT/RAG
- Baseline strategy (SMA/ATR/LightGBM) làm control
- Meta-signal engine (ensemble + cost filter)
- Risk manager (sizing, drawdown, kill switch)
- MT5 executor (order_check + order_send hoặc dry_run)
- Backtest engine với walk-forward
- Logging + monitoring + alert cơ bản
```

### Out-of-scope (giai đoạn sau)

```text
- High-frequency trading (sub-second)
- Tự động ML retraining loop
- Production-grade Kafka streaming
- Multi-broker arbitrage
- Multi-account portfolio management nâng cao
```

---

## 1.3 Symbol và timeframe ưu tiên

```text
EURUSD  M15/H1   - Forex major, spread thấp, dễ test
XAUUSD  M15/H1   - Gold, biến động cao, news-driven
NAS100  M15/H1   - Index CFD, có yếu tố macro
US30    M15/H1   - Index CFD
BTCUSD  M15/H1   - Crypto CFD nếu broker hỗ trợ
```

Bắt đầu với **1 symbol + 1 timeframe**. Mở rộng sau khi pipeline ổn.

---

## 1.4 Nguyên tắc thiết kế bất di bất dịch

1. **Separation of concerns**: model dự báo ≠ risk ≠ executor
2. **Hard limits trước soft signals**: risk manager đứng trên model
3. **Auditability**: mọi forecast, signal, order đều log đầy đủ
4. **Fail-safe defaults**: lỗi không rõ ràng → HOLD, không trade
5. **Closed-bar only**: không dùng nến đang chạy để forecast
6. **Cost-aware**: edge phải vượt spread + commission + slippage
7. **No single point of trust**: không model nào được tin tuyệt đối
8. **Reversible deployment**: dry_run → demo → live, có rollback

---

## 1.5 Stakeholder & vai trò

| Vai trò | Trách nhiệm |
|---|---|
| Quant lead | Định nghĩa edge, threshold, weight, risk rule |
| ML engineer | Triển khai adapter model, tuning, evaluation |
| Backend engineer | MT5 connector, executor, monitoring |
| Risk officer (nếu có) | Phê duyệt risk config trước khi live |
| Reviewer | Code review, audit log review |

---

## 1.6 Các tiêu chí "ready to go live"

Hệ thống chỉ được go-live khi tất cả các điều kiện sau pass:

```text
[ ] Backtest out-of-sample positive sau cost
[ ] Backtest thắng baseline ít nhất 6 tháng OOS
[ ] Demo trading 2-4 tuần không lỗi execution nghiêm trọng
[ ] Drawdown trong giới hạn cấu hình (<= 8%)
[ ] Kill switch test pass
[ ] order_check không bao giờ fail vì lỗi config
[ ] Logging đủ để truy vết mọi trade
[ ] Người vận hành biết cách dừng hệ thống an toàn
[ ] Risk per trade khởi điểm <= 0.1%
```

---

## 1.7 Định nghĩa "thành công"

Thành công của dự án **không phải** lợi nhuận tuyệt đối trong vài tuần đầu, mà là:

```text
- Pipeline chạy ổn định, không crash silent
- Mọi trade đều có audit trail
- Drawdown không vượt limit
- AI ensemble có chứng minh được edge sau cost so với baseline
- Hệ thống đủ an toàn để có thể tăng size dần khi đã tin tưởng
```

Nếu sau 4 tuần demo mà ensemble không thắng baseline + cost, **không go live**, quay lại tuning ở giai đoạn 7.
