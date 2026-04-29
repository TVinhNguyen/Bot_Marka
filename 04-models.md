# 04. Vai trò chi tiết của từng mô hình AI

## 4.1 Bảng phân vai

| Model | Vai trò | Loại signal | Có quyền ra lệnh? |
|---|---|---|---|
| TimesFM | Forecast chuỗi thời gian tổng quát | expected_return + uncertainty | Không |
| Kronos | Forecast OHLCV/K-line tài chính | direction_prob + return | Không |
| Chronos / Chronos-2 | Forecast xác suất + multivariate | quantiles + return | Không |
| FinGPT / FinBERT / RAG | Sentiment + event_risk | sentiment_score + permission | Không |
| Baseline (SMA/ATR/LightGBM) | Strategy control | direction | Không |
| Risk manager | Sizing + hard limits | approve/reject + lot/SL/TP | **Phê duyệt/chặn** |
| MT5 executor | order_check + order_send | trạng thái order | **Execution** |

---

## 4.2 TimesFM

### 4.2.1 Mục đích

Forecast các chuỗi tổng quát: log-return, volatility, ATR normalized, spread normalized.

### 4.2.2 Input

```python
target_options = ["log_return", "close", "realized_volatility", "atr_norm"]
context_length = 512   # nến
horizon       = 8      # nến tới (M15 -> 2 giờ)
```

### 4.2.3 Output schema

```python
{
    "model": "timesfm",
    "horizon": 8,
    "expected_return": 0.0012,
    "uncertainty": 0.0008,        # quantile width hoặc std
    "score": 0.43,                # normalized [-1, +1]
    "direction": "BUY",
    "metadata": {
        "p10": -0.0004,
        "p50": 0.0006,
        "p90": 0.0030,
        "context_length": 512,
        "target": "log_return",
    }
}
```

### 4.2.4 Câu hỏi TimesFM trả lời

```text
- Trong H nến tới, return kỳ vọng có vượt chi phí giao dịch không?
- Forecast có chắc không hay quantile rộng?
- Volatility sắp tăng hay giảm?
```

### 4.2.5 Hạn chế

- Không hiểu cấu trúc nến (high/low chỉ là biến phụ)
- Có thể bias bởi chu kỳ chuỗi giả
- Cần normalize cẩn thận khi đổi symbol

---

## 4.3 Kronos

### 4.3.1 Mục đích

Forecast trực tiếp trên OHLCV/K-line. Đây là **model chính** cho dữ liệu tài chính.

### 4.3.2 Input

```python
columns = ["open", "high", "low", "close", "volume"]
# nếu broker cung cấp, thêm 'amount' (giá trị giao dịch)
context_length = 512
horizon       = 8
```

### 4.3.3 Output schema

```python
{
    "model": "kronos",
    "horizon": 8,
    "predicted_ohlc": [...],       # list dict OHLC theo nến forecast
    "expected_return": 0.0015,
    "direction_probability": 0.64, # P(close_H > close_now)
    "score": 0.55,
    "direction": "BUY",
    "metadata": {
        "predicted_high_max": ...,
        "predicted_low_min": ...,
    }
}
```

### 4.3.4 Câu hỏi Kronos trả lời

```text
- Cấu trúc nến tới giống breakout, mean-reversion hay chop?
- Close sau H nến cao hơn hay thấp hơn hiện tại?
- High/low forecast có đủ không gian cho SL/TP không?
```

### 4.3.5 Hạn chế

- Ít kiểm chứng độc lập so với TimesFM/Chronos
- Cần pin commit và verify lại reproducibility
- Có thể overfit với pattern lịch sử của broker cụ thể

### 4.3.6 Áp dụng cho MT5

```text
EURUSD M15/H1, XAUUSD M15/H1, NAS100 M15/H1, US30 M15/H1, BTCUSD M15/H1
```

---

## 4.4 Chronos / Chronos-2

### 4.4.1 Mục đích

Probabilistic forecast độc lập, dùng để cross-check TimesFM/Kronos. Chronos-2 hỗ trợ multivariate/covariate.

### 4.4.2 Input

```python
target = log_return
covariates_optional = [
    "dxy_return",
    "us10y_yield_change",
    "vix",
    "spx_return",
    "oil_return",
    "event_dummy",
]
```

### 4.4.3 Output schema

```python
{
    "model": "chronos",
    "horizon": 8,
    "expected_return": 0.0007,
    "p10": -0.0004,
    "p50": 0.0006,
    "p90": 0.0018,
    "uncertainty": 0.0022,        # p90 - p10
    "score": 0.31,
    "direction": "BUY",
}
```

### 4.4.4 Câu hỏi Chronos trả lời

```text
- Forecast xác suất có cùng hướng TimesFM/Kronos?
- Biến phụ macro/cross-asset có ủng hộ signal?
- Phân phối có lệch dương/âm rõ rệt?
```

### 4.4.5 Hạn chế

- Cần dữ liệu covariate đồng bộ timestamp
- Multivariate có thể overfit nếu covariate quá nhiều

---

## 4.5 FinGPT / FinBERT / RAG

### 4.5.1 Mục đích

Lớp **text intelligence**: sentiment, event_risk, summary tin tức.

### 4.5.2 Input

```python
news_documents = retrieve_recent_news(
    symbol=symbol,
    lookback_hours=24,
    sources=["reuters", "bloomberg", "fxstreet", ...]
)
macro_calendar = get_upcoming_events(window_hours=4)
```

### 4.5.3 Output schema

```python
{
    "model": "fingpt_rag",
    "sentiment_score": 0.35,      # [-1, +1]
    "event_risk": 0.70,           # [0, 1]
    "summary": "Tin tích cực, sắp có CPI nên rủi ro cao",
    "direction_bias": "BUY",
    "trade_permission": "REDUCE_SIZE_OR_HOLD",   # FULL | REDUCE_SIZE_OR_HOLD | BLOCK
    "metadata": {
        "doc_count": 12,
        "newest_age_minutes": 17,
        "next_event_minutes": 35,
    }
}
```

### 4.5.4 Sources phù hợp

```text
Forex / XAUUSD / Index:
  FOMC, CPI, NFP, jobs report
  Fed/ECB/BOJ/BOE speeches
  geopolitical risk
  DXY/yields headlines
  gold/oil macro news

Stock CFD:
  earnings report, SEC filings
  analyst rating
  sector news
```

### 4.5.5 Quan trọng

```text
- event_risk cao -> FinGPT có thể CHẶN trade dù model khác bullish
- newest_age > threshold -> giảm trọng số sentiment
- thiếu dữ liệu -> set sentiment_weight = 0, KHÔNG block toàn hệ thống
```

### 4.5.6 Hạn chế

- Latency: nếu tin chậm, signal hết hiệu lực
- Có thể bị "stale news" nếu không filter timestamp
- LLM có thể hallucinate; phải kết hợp với FinBERT cho calibration

---

## 4.6 Baseline (control strategy)

### 4.6.1 Mục đích

Không phải để trade chính, mà để **kiểm chứng AI ensemble có thật sự tốt hơn**.

### 4.6.2 Lựa chọn

```text
- SMA crossover + ATR filter
- Logistic regression trên features cơ bản (return lag, volatility)
- LightGBM trên feature set giống AI
```

### 4.6.3 Output schema

Giống `ModelForecast` nhưng `metadata.kind = "baseline"`.

### 4.6.4 Quy tắc go-live

```text
Nếu AI ensemble không vượt baseline sau cost (out-of-sample),
KHÔNG go-live. Quay lại tuning ensemble.
```

---

## 4.7 Interface chuẩn `ModelForecast`

```python
from dataclasses import dataclass, field

@dataclass
class ModelForecast:
    model_name: str
    direction: str              # BUY | SELL | HOLD
    expected_return: float
    uncertainty: float
    raw_score: float            # trước normalize
    score: float                # sau normalize, [-1, +1]
    confidence: float           # [0, 1]
    horizon: int
    reason: str
    metadata: dict = field(default_factory=dict)
```

Tất cả adapter **phải** trả về schema này. Adapter nào không thể trả thì không được merge vào ensemble.

---

## 4.8 Score normalization

Mỗi adapter chịu trách nhiệm chuyển raw output về `score ∈ [-1, +1]`:

```python
# TimesFM
score = clip(expected_return / (k * historical_std), -1, +1)

# Kronos
score = clip(2 * direction_probability - 1, -1, +1)
# hoặc kết hợp với expected_return / atr
score = sign(expected_return) * min(1, |expected_return| / atr)

# Chronos
score = clip(p50 / (p90 - p10 + eps) * scale, -1, +1)

# FinGPT
score = sentiment_score   # đã ở [-1, +1]
```

Hệ số `k`, `scale` là hyperparameter, được tune trong giai đoạn 7.

---

## 4.9 Adapter pattern (skeleton)

```python
class TimesFMAdapter:
    def __init__(self, model, cfg): ...
    def predict(self, df: pd.DataFrame) -> ModelForecast: ...

class KronosAdapter:
    def predict(self, df: pd.DataFrame) -> ModelForecast: ...

class ChronosAdapter:
    def predict(self, df, covariates=None) -> ModelForecast: ...

class FinGPTAdapter:
    def predict(self, symbol: str, news_ctx) -> ModelForecast: ...

class BaselineAdapter:
    def predict(self, df) -> ModelForecast: ...
```

Tất cả implement cùng interface để ensemble engine không cần biết model nào.

---

## 4.10 Failure handling

Nếu một adapter raise exception hoặc trả invalid:

```text
- Log error chi tiết (model_name, traceback, input hash)
- Set adapter.score = 0, adapter.confidence = 0
- Scale lại weight của các model còn lại
- Nếu > 50% adapter fail -> ensemble trả HOLD
```

Không bao giờ "tin tưởng" model còn lại để tự ý trade khi thiếu input.
