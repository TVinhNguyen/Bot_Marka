# 18. Pitfalls & cách phòng tránh

## 18.1 Bẫy về dữ liệu

### 1. Dùng nến đang chạy thay vì nến đã đóng
**Triệu chứng**: backtest đẹp nhưng live tệ
**Phòng tránh**:
```text
- closed_bar_only=true mặc định
- Slice df.iloc[:-1] trước feature builder
- Test: ép input chứa nến running -> adapter raise hoặc skip
```

### 2. Look-ahead bias trong feature
**Triệu chứng**: backtest Sharpe quá cao (>3 cho intraday forex)
**Phòng tránh**:
```text
- Mọi feature tại bar t chỉ dùng data <= t-1
- rolling().shift(1) khi cần
- Test backtest với fixture deterministic và assert kết quả không đổi
- Audit code review tập trung vào time alignment
```

### 3. Future leak qua news timestamp
**Triệu chứng**: sentiment quá tốt
**Phòng tránh**:
```text
- News dùng cho bar t phải có publish_ts <= bar_t.open
- Embedding store giữ publish_ts gốc
- Retrieval filter strict timestamp
```

### 4. Cross-asset chưa align timezone
**Phòng tránh**:
```text
- Mọi storage UTC
- Forward-fill có giới hạn (max_gap)
- Verify đồng bộ bằng correlation sanity
```

### 5. Spread giả định cố định trong backtest
**Phòng tránh**:
```text
- Dùng spread thực từ ticks nếu có
- Stress test với spread 1.5x-2x
- Phân biệt session có spread cao (rollover, tin)
```

---

## 18.2 Bẫy về model

### 6. Forecast raw price thay vì return
**Phòng tránh**: dùng log_return / pct_change. Raw close có level non-stationary.

### 7. Một model dominate ensemble
**Triệu chứng**: weight sau tune > 0.7 cho 1 model
**Phòng tránh**:
```text
- Ràng buộc weight max trong tune (vd <= 0.5)
- Sanity: bỏ model dominate -> ensemble không sụp hoàn toàn
- Track per-model attribution
```

### 8. Models cùng học từ một nguồn -> agreement giả
**Phòng tránh**:
```text
- Đảm bảo input khác nhau (TimesFM dùng return, Kronos dùng OHLCV, FinGPT dùng news)
- Đo correlation forecast giữa model
- Nếu correlation > 0.9 -> agreement không có giá trị thông tin
```

### 9. FinGPT đọc tin chậm, signal hết hiệu lực
**Phòng tránh**:
```text
- News pipeline có SLO độ trễ
- Time decay weight cho sentiment
- Nếu newest_age > threshold -> sentiment_weight = 0
- Không trade vào tin trong news_window
```

### 10. Adapter raise exception silent
**Phòng tránh**:
```text
- Try/except quanh predict + log ERROR
- Set score = 0, weight rescale
- Counter alert nếu adapter fail > N lần / giờ
```

### 11. Model drift sau vài tuần live
**Phòng tránh**:
```text
- Track Brier score, accuracy rolling
- Alert nếu accuracy < random baseline 2 tuần
- Có quy trình retrain/refit baseline định kỳ
```

---

## 18.3 Bẫy về ensemble

### 12. Tune weight trên test set
**Phòng tránh**:
```text
- Walk-forward strict
- Lưu weight đã chọn cho mỗi window
- Không sửa weight sau khi đã thấy OOS metric
```

### 13. Threshold quá thấp -> trade quá nhiều
**Phòng tránh**:
```text
- Lọc bằng edge_to_cost_ratio >= 1.5
- Track turnover, exposure_time
- Nếu trade > expected -> raise threshold
```

### 14. Agreement giả vì correlation cao
Xem #8.

### 15. Ignore event_risk vì FinGPT fail
**Phòng tránh**:
```text
- Khi FinGPT fail, mặc định event_risk = 0.5 (conservative)
- Không bỏ qua hoàn toàn
- Kết hợp macro calendar rule cứng (no-trade window)
```

---

## 18.4 Bẫy về risk

### 16. Lot sizing sai vì tick value khác giữa symbol
**Phòng tránh**:
```text
- Luôn dùng mt5.symbol_info để lấy tick_value, tick_size, contract_size
- Test sizing cho từng symbol (EURUSD, XAUUSD, NAS100)
- mt5.order_calc_margin để verify margin
```

### 17. Stop level broker chặn SL/TP quá gần
**Phòng tránh**:
```text
- info.trade_stops_level
- Đẩy SL/TP ra xa stop_level + buffer
- order_check sẽ reject nếu vi phạm -> log + skip
```

### 18. Margin insufficient -> order_send fail
**Phòng tránh**:
```text
- order_calc_margin trước khi send
- margin_safety = 0.8 (chừa buffer)
- Track free_margin live
```

### 19. Quên kill switch
**Phòng tránh**:
```text
- Test kill switch hàng tuần (drill)
- File sentinel + endpoint + Telegram command
- Document trong runbook
```

### 20. Daily/weekly soft breaker không trigger
**Phòng tránh**:
```text
- Test bằng cách inject lịch sử PnL giả vào snapshot
- Property test với consecutive_losses
```

---

## 18.5 Bẫy về execution

### 21. Double order do retry
**Phòng tránh**:
```text
- Idempotency key
- KHÔNG retry order_send tự động
- Reconcile sau timeout
```

### 22. Filling mode sai cho symbol
**Phòng tránh**:
```text
- Đọc info.filling_mode -> chọn FOK/IOC/RETURN
- Test cho từng symbol
```

### 23. Deviation quá nhỏ -> requote liên tục
**Phòng tránh**:
```text
- deviation_points >= spread_max + slippage_buffer
- Track requote rate
```

### 24. Magic number trùng với EA khác
**Phòng tránh**:
```text
- Magic duy nhất cho hệ thống
- Reconcile khi khởi động phát hiện magic lạ -> alert
```

### 25. Crash giữa order_send và DB write
**Phòng tránh**:
```text
- Reconcile khi restart: query positions theo magic
- Idempotent insert (UPSERT theo ticket)
- Health check sau restart
```

---

## 18.6 Bẫy về backtest

### 26. Optimize quá nhiều hyperparameter
**Phòng tránh**:
```text
- Limit số fit per window
- Rule "tăng tham số -> phải có cải thiện OOS đáng kể"
- Cross-symbol validation
```

### 27. Slippage 0 trong backtest
**Phòng tránh**:
```text
- Slippage buffer >= 5 points cho forex major
- Test với 2x slippage
- Đo slippage thực tế khi demo, cập nhật buffer
```

### 28. Survivorship bias (cổ phiếu)
Cho stock CFD: dùng dataset có symbol delist.

### 29. Backtest period không đại diện
**Phòng tránh**:
```text
- Phải có giai đoạn high-vol (2020 covid, 2022 rate hike)
- Phải có giai đoạn ranging
- Không chỉ chọn giai đoạn lợi cho strategy
```

---

## 18.7 Bẫy về vận hành

### 30. Clock drift
**Phòng tránh**: NTP, alert nếu drift > 5s.

### 31. MT5 disconnect không phát hiện
**Phòng tránh**:
```text
- terminal_info() check mỗi tick
- last_tick_age metric
- Alert critical nếu disconnect > 30s
```

### 32. Disk full dừng log
**Phòng tránh**:
```text
- Log rotation
- Monitor disk usage, alert ở 70%, kill switch ở 95%
- Audit logs có retention policy
```

### 33. Config thay đổi không ai biết
**Phòng tránh**:
```text
- Diff log mỗi reload
- Telegram alert khi thay đổi risk/execution
- Git history + 4-eyes
```

### 34. Operator bấm nhầm (kill switch không có)
**Phòng tránh**:
```text
- Có nút kill switch dễ thấy + xác nhận
- Telegram bot command /stop
- Tài liệu runbook rõ ràng
```

---

## 18.8 Bẫy về kỳ vọng

### 35. Tin AI tuyệt đối
**Phòng tránh**: agent không tự trade, risk manager là gate cứng.

### 36. Quên phí và slippage
**Phòng tránh**: edge_to_cost_ratio >= 1.5, cost trừ trước threshold.

### 37. Tăng size quá nhanh sau vài lần thắng
**Phòng tránh**:
```text
- Roadmap tăng size theo tuần, không theo PnL
- 4-tuần soak ở mỗi level
- Risk officer duyệt mỗi lần tăng
```

### 38. Coi backtest = guarantee
**Phòng tránh**:
```text
- Live luôn worse hơn backtest (slippage, latency, regime change)
- Đặt expectation 70-80% Sharpe của backtest
- Có drift detection
```

---

## 18.9 Sổ tay nhanh

| Triệu chứng | Khả năng cao | Hành động |
|---|---|---|
| Backtest Sharpe > 3 intraday | Look-ahead | Audit code |
| Live PnL << backtest | Drift / slippage | Track per-model accuracy |
| Order_send timeout | Broker / network | Reconcile, không retry |
| Drawdown spike | Regime change / model fail | Soft breaker, review |
| Trades/day > expected | Threshold quá thấp | Raise threshold |
| Sentiment luôn 0 | News pipeline down | Alert + degrade gracefully |
| Adapter exception bão | Model lib lỗi / version | Pin, rollback |
| Spread spike | Tin / rollover | News window, halt |
