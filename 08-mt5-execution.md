# 08. MT5 execution layer

## 8.1 Hai option triển khai

### Option A — Python điều khiển MT5 trực tiếp (MVP)

```text
Python service
  -> MetaTrader5.initialize()
  -> copy_rates_from / copy_ticks_range
  -> model inference + ensemble + risk
  -> order_check
  -> order_send
```

**Ưu**: nhanh, dễ debug, dễ tích hợp model AI
**Nhược**: phụ thuộc MT5 terminal đang mở, không chạy được trong Strategy Tester

### Option B — MQL5 EA executor + Python AI server (production)

```text
MQL5 EA:
  - OnTimer / OnTick event
  - lấy giá hiện tại
  - gọi Python server (REST/ZMQ)
  - nhận signal JSON
  - tự kiểm tra spread/SL/TP/position
  - OrderSend bằng MQL5 API

Python AI server:
  - FastAPI/ZeroMQ endpoint
  - nhận request từ EA
  - lấy thêm data, chạy model
  - trả ensemble + risk decision (signal only)
```

**Ưu**: execution nằm trong terminal, low-latency, dùng VPS Windows tốt hơn
**Nhược**: cần viết bridge, audit chéo Python/MQL5

---

## 8.2 Khi nào chọn cái nào

| Tình huống | Khuyến nghị |
|---|---|
| MVP, dry_run, demo | Option A |
| Single symbol, ít trades/day | Option A |
| Backtest trong Strategy Tester | Option B |
| Production live, latency-sensitive | Option B |
| Nhiều account / nhiều symbol | Option B |

---

## 8.3 Option A — chi tiết

### 8.3.1 Initialize

```python
import MetaTrader5 as mt5
import os

def init_mt5(cfg):
    ok = mt5.initialize(
        path=cfg["mt5"]["terminal_path"] or None,
        login=cfg["mt5"]["login"],
        password=os.environ[cfg["mt5"]["password_env"]],
        server=cfg["mt5"]["server"],
        timeout=60_000,
        portable=False,
    )
    if not ok:
        raise RuntimeError(f"mt5 init failed: {mt5.last_error()}")
    return mt5
```

### 8.3.2 Build order request

```python
def build_request(symbol, side, volume, sl, tp, magic, comment, deviation=20):
    info = mt5.symbol_info(symbol)
    if info is None or not info.visible:
        mt5.symbol_select(symbol, True)
        info = mt5.symbol_info(symbol)

    tick = mt5.symbol_info_tick(symbol)
    price = tick.ask if side == "BUY" else tick.bid

    return {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       symbol,
        "volume":       volume,
        "type":         mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL,
        "price":        price,
        "sl":           sl,
        "tp":           tp,
        "deviation":    deviation,
        "magic":        magic,
        "comment":      comment,
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": pick_filling_mode(info),
    }
```

### 8.3.3 Filling mode

```python
def pick_filling_mode(info):
    flags = info.filling_mode
    if flags & mt5.SYMBOL_FILLING_FOK:
        return mt5.ORDER_FILLING_FOK
    if flags & mt5.SYMBOL_FILLING_IOC:
        return mt5.ORDER_FILLING_IOC
    return mt5.ORDER_FILLING_RETURN
```

### 8.3.4 order_check + order_send

```python
def submit(req, dry_run=False):
    check = mt5.order_check(req)
    if check is None or check.retcode != mt5.TRADE_RETCODE_DONE:
        return {"ok": False, "stage": "check",
                "retcode": getattr(check, "retcode", None),
                "comment": getattr(check, "comment", None)}

    if dry_run:
        return {"ok": True, "stage": "dry_run", "request": req, "check": check._asdict()}

    result = mt5.order_send(req)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        return {"ok": False, "stage": "send",
                "retcode": getattr(result, "retcode", None),
                "comment": getattr(result, "comment", None)}

    return {"ok": True, "stage": "send", "ticket": result.order, "result": result._asdict()}
```

### 8.3.5 Reconnect logic

```python
def ensure_connected(retries=3):
    for i in range(retries):
        if mt5.terminal_info() is not None:
            return True
        time.sleep(2 ** i)
        mt5.shutdown()
        init_mt5(cfg)
    raise RuntimeError("MT5 reconnect failed")
```

---

## 8.4 Option B — chi tiết

### 8.4.1 Architecture

```text
[ MT5 Terminal (Windows VPS) ]              [ AI Server (Linux/GPU) ]
  EA: ai_executor.mq5                          FastAPI / ZeroMQ
   - OnTimer 5s                                  - /predict
   - http_request_post(...)                      - /risk
   - parse JSON                                  - returns:
   - OrderSend                                       direction, volume,
                                                     sl, tp, magic
```

### 8.4.2 EA skeleton (MQL5 pseudocode)

```mql5
input string AIServerURL = "http://ai-server:8080/predict";
input int    Magic       = 26042901;
input int    DeviationPt = 20;

void OnTimer() {
    if (PositionsTotalForSymbol(_Symbol) >= MaxPosPerSymbol) return;

    string body = BuildRequestJson(_Symbol, _Period, AccountInfo());
    string response = HttpPost(AIServerURL, body, 5000);
    if (StringLen(response) == 0) return;

    Signal sig = ParseSignal(response);
    if (sig.direction == "HOLD") return;

    if (!sig.approved) return;
    if (!CheckSpread(_Symbol)) return;

    MqlTradeRequest req = BuildRequest(sig);
    MqlTradeCheckResult chk;
    if (!OrderCheck(req, chk)) return;

    MqlTradeResult res;
    OrderSend(req, res);
}
```

### 8.4.3 Bridge protocol

```json
POST /predict
{
  "symbol":       "EURUSD",
  "timeframe":    "M15",
  "ts":           "2026-04-29T14:00:00Z",
  "bars":         [...],          // optional, EA có thể gửi bars
  "account": {
    "equity":     10000.0,
    "balance":    10000.0,
    "currency":   "USD"
  },
  "open_positions": []
}
```

```json
200 OK
{
  "approved":  true,
  "direction": "BUY",
  "volume":    0.05,
  "sl":        1.08230,
  "tp":        1.08680,
  "magic":     26042901,
  "comment":   "ai-mt5-multimodel",
  "reason":    "score_pass|risk_pass",
  "audit_id":  "f3c1...e9"
}
```

### 8.4.4 Lưu ý

- **Authenticate**: token shared header, IP whitelist
- **Idempotency**: EA gửi `client_request_id` để tránh double order
- **Heartbeat**: EA ping `/health` mỗi 30s; nếu fail -> không trade
- **Fallback**: EA có rule "no signal in 60s -> không tự trade"

---

## 8.5 Magic number & comment

```yaml
execution:
  magic: 26042901
  comment_prefix: "ai-mt5-mm"
```

Format comment:

```text
ai-mt5-mm|<symbol>|<timeframe>|<signal_id>
```

Magic number duy nhất giúp:
- Lọc position của bot khỏi trade thủ công
- Audit và reconcile khi crash

---

## 8.6 Idempotency & retry

```text
- Mọi order_send phải có client request id (lưu trong DB trước khi send)
- Nếu order_send timeout: KHÔNG retry tự động. Reconcile bằng cách:
    1. Đợi 5-10s
    2. Query positions/history theo magic + comment
    3. Nếu thấy ticket -> mark success
    4. Nếu không -> alert operator, KHÔNG tự retry
- Double-send là rủi ro lớn hơn miss-send
```

---

## 8.7 Position management ngoài entry

```text
- Trailing SL: do EA hoặc Python tick handler thực hiện
- Move-to-breakeven: tùy chọn cấu hình
- Partial close: chỉ bật khi đã được test backtest
- Time-based exit: đóng sau N nến nếu không hit SL/TP
```

Tất cả các luật quản lý vị thế phải được mô tả trong config và test backtest. Không hardcode.

---

## 8.8 Reconciliation (mỗi lần khởi động)

```text
1. Query mt5.positions_get(magic=cfg.magic) -> set A
2. Query DB trades WHERE status="open" -> set B
3. So sánh:
   - A \ B: position trên broker mà DB không biết -> alert (manual)
   - B \ A: DB nghĩ đang mở nhưng broker đã đóng -> sync history
   - A ∩ B: cập nhật giá hiện tại, PnL
4. Kill switch nếu lệch nghiêm trọng
```

---

## 8.9 Account safety pre-flight

Trước khi cho phép `dry_run=False`:

```text
[ ] Đúng login, đúng server, đúng broker
[ ] Account type là demo nếu chưa qua giai đoạn 9
[ ] account.trade_allowed = True
[ ] account.trade_expert = True
[ ] symbol.trade_mode = SYMBOL_TRADE_MODE_FULL
[ ] terminal.connected = True
[ ] terminal.community_account đã đăng nhập (nếu cần)
```

---

## 8.10 Logging contract

Mỗi lần submit:

```json
{
  "ts": "2026-04-29T14:00:00Z",
  "stage": "send",
  "symbol": "EURUSD",
  "side": "BUY",
  "volume": 0.05,
  "sl": 1.08230,
  "tp": 1.08680,
  "request_hash": "...",
  "check_retcode": 0,
  "send_retcode": 10009,
  "ticket": 1234567,
  "execution_ms": 38,
  "spread_at_submit": 14,
  "deviation_used": 4,
  "audit_id": "f3c1...e9"
}
```

Lưu vào `trades.csv` + DB. **Không xóa** log cũ.
