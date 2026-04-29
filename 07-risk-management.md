# 07. Risk management

## 7.1 Triết lý

Risk manager là **người gác cổng cuối cùng** trước khi lệnh đến MT5. Nó:

- **Không** xem lại forecast (đã được ensemble xử lý)
- **Có quyền** override approve/reject
- **Có quyền** hạ size, ép SL/TP, từ chối symbol
- **Bị ràng buộc** bởi hard limit trong config, không thể bị model bypass

```text
Nếu risk manager nói NO -> không có order_send.
Đây là rule không thương lượng.
```

---

## 7.2 Input

```python
{
    "ts": "2026-04-29T14:00:00Z",
    "symbol": "EURUSD",
    "side": "BUY",                    # từ ensemble
    "final_score": 0.37,
    "confidence": 0.68,
    "agreement": 0.80,
    "atr": 0.0011,
    "spread_points": 14,
    "event_risk": 0.30,
    "regime": "trend",
    "account": {
        "equity": 10000.0,
        "balance": 10000.0,
        "margin_used": 0.0,
        "free_margin": 10000.0,
        "currency": "USD",
    },
    "open_positions": [],
    "today_stats": {
        "trades": 1,
        "realized_pnl_pct": -0.004,
        "consecutive_losses": 1,
    },
    "drawdown_pct": 0.012,
}
```

---

## 7.3 Output

```python
{
    "approved": True,
    "side": "BUY",
    "volume": 0.05,
    "sl": 1.08230,
    "tp": 1.08680,
    "magic": 26042901,
    "reason": "score_pass|risk_pass|spread_pass",
    "rejected_by": [],
}
```

Nếu reject:

```python
{
    "approved": False,
    "rejected_by": ["max_daily_loss_breached"],
    "reason": "daily_loss=-0.022 > limit=-0.02",
}
```

---

## 7.4 Hard limits (config)

```yaml
risk:
  base_risk_per_trade:    0.002    # 0.2% equity
  max_risk_per_trade:     0.005    # 0.5% equity
  min_risk_per_trade:     0.0005   # 0.05% equity
  max_daily_loss:         0.02     # 2% equity / ngày -> dừng
  max_total_drawdown:     0.08     # 8% equity tích lũy -> kill switch
  max_positions_per_symbol: 1
  max_total_positions:      3
  max_trades_per_day:       5
  max_consecutive_losses:   3      # > limit -> giảm size hoặc HOLD

  sl_atr_min: 1.2
  sl_atr_max: 2.5
  tp_atr:     2.0
  rr_min:     1.0                  # tp_distance / sl_distance >= 1

  spread_max_points:
    EURUSD: 25
    XAUUSD: 60
    NAS100: 200
    BTCUSD: 200

  news_window_minutes:
    high:   [-30, +30]
    medium: [-10, +15]

  kill_switch:
    enabled: true
    triggers:
      drawdown_pct: 0.08
      manual_file:  "/var/run/ai-mt5/STOP"
```

---

## 7.5 Pipeline kiểm tra

```python
def evaluate(req, cfg, account, market) -> RiskDecision:
    if kill_switch_active(cfg):
        return reject("kill_switch_active")

    if account_drawdown(account) >= cfg.max_total_drawdown:
        trigger_kill_switch("drawdown_breached")
        return reject("max_drawdown_breached")

    if today_loss(account) <= -cfg.max_daily_loss:
        return reject("max_daily_loss_breached")

    if today_trades(account) >= cfg.max_trades_per_day:
        return reject("max_trades_per_day_reached")

    if positions_for(req.symbol) >= cfg.max_positions_per_symbol:
        return reject("max_positions_per_symbol_reached")

    if total_open_positions(account) >= cfg.max_total_positions:
        return reject("max_total_positions_reached")

    if market.spread_points > cfg.spread_max_points[req.symbol]:
        return reject("spread_too_wide")

    if in_news_window(req.ts, cfg.news_window_minutes):
        return reject("inside_news_window")

    sl, tp = compute_sl_tp(req, market, cfg)
    if not validate_sl_tp(sl, tp, market, cfg):
        return reject("invalid_sl_tp")

    volume = compute_volume(req, account, market, cfg)
    if volume <= 0:
        return reject("volume_zero_after_sizing")

    return approve(side=req.side, volume=volume, sl=sl, tp=tp)
```

Mọi reject phải log với reason. Nhiều reject cùng lúc -> log tất cả vào `rejected_by`.

---

## 7.6 Position sizing

### 7.6.1 Công thức

```python
effective_risk = base_risk_per_trade
effective_risk *= confidence       # [0,1]
effective_risk *= agreement        # [0,1]
effective_risk = clip(effective_risk, min_risk, max_risk)

money_at_risk = equity * effective_risk

sl_distance_price = sl_atr_multiplier * atr
loss_per_lot      = sl_distance_price / tick_size * tick_value

raw_volume = money_at_risk / loss_per_lot
volume     = round_to_lot_step(raw_volume, lot_step, volume_min, volume_max)
```

### 7.6.2 Lot validation theo broker

```python
info = mt5.symbol_info(symbol)
volume_min  = info.volume_min
volume_max  = info.volume_max
volume_step = info.volume_step

volume = max(volume_min, min(volume_max, round_step(volume, volume_step)))
```

Nếu `volume < volume_min` -> reject với reason `"volume_below_min"`.

### 7.6.3 Margin check

```python
margin_required = mt5.order_calc_margin(order_type, symbol, volume, price)
if margin_required > account.free_margin * cfg.margin_safety:
    return reject("insufficient_margin")
```

`margin_safety = 0.8` mặc định để có buffer.

---

## 7.7 SL / TP

### 7.7.1 SL

```python
sl_distance = clip(
    sl_atr_multiplier * atr,
    min = sl_atr_min * atr,
    max = sl_atr_max * atr,
)

if side == "BUY":
    sl = entry_price - sl_distance
else:
    sl = entry_price + sl_distance
```

### 7.7.2 TP

```python
tp_distance = tp_atr * atr
if side == "BUY":
    tp = entry_price + tp_distance
else:
    tp = entry_price - tp_distance

assert tp_distance / sl_distance >= cfg.rr_min
```

### 7.7.3 Stop level broker

```python
stop_level_points = info.trade_stops_level
min_distance = stop_level_points * info.point

if abs(sl - entry_price) < min_distance: ...   # đẩy SL ra xa
if abs(tp - entry_price) < min_distance: ...   # đẩy TP ra xa
```

---

## 7.8 Kill switch

### 7.8.1 Trigger tự động

```text
- drawdown >= max_total_drawdown
- > N execution error trong 5 phút
- broker disconnect quá lâu
- spread > 5x median trong 10 nến
```

### 7.8.2 Trigger thủ công

```text
- File sentinel /var/run/ai-mt5/STOP
- Endpoint /admin/kill (production)
- Telegram bot command /stop (gửi cho operator)
```

### 7.8.3 Behavior khi active

```text
1. Mọi quyết định mới: reject với "kill_switch_active"
2. Optional: đóng các position đang mở (cấu hình `kill_switch_close_positions`)
3. Alert ngay lập tức (Telegram/email/PagerDuty)
4. Ghi log + persist trạng thái để restart không tự động bật lại
5. Restart phải có manual confirmation (xóa file sentinel)
```

---

## 7.9 Daily / weekly soft circuit breakers

```yaml
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

Soft breaker không trigger kill switch toàn cục, chỉ thay đổi tham số.

---

## 7.10 Test risk engine

```text
- Property-based test với hypothesis: lot >= volume_min, lot <= max_risk_per_trade
- Test mọi rule reject: ép input vi phạm, expect reject với đúng reason
- Test sizing với confidence/agreement biên (0, 1)
- Test broker stop_level edge case
- Test margin insufficient
- Test kill switch
- Test news window
```

Risk engine **phải** đạt 90%+ coverage trước khi go live.

---

## 7.11 Post-trade attribution

Sau mỗi trade close, lưu:

```text
- forecast của từng model
- ensemble result
- risk decision input/output
- order request, order_check, order_send response
- exit reason: SL hit | TP hit | manual close | EOD | trailing
- realized PnL
- slippage thực tế vs slippage_buffer
```

Dùng để tuning weight, threshold và phát hiện model drift.
