# 06. Meta-signal engine

## 6.1 Mục đích

Kết hợp output từ nhiều adapter thành một quyết định cuối: BUY / SELL / HOLD + confidence + reason. Trừ chi phí, kiểm tra agreement, regime, event_risk.

Engine này **không** quyết định lot, **không** gửi order. Chỉ trả `EnsembleResult`.

---

## 6.2 Input

```python
forecasts: list[ModelForecast] = [
    timesfm_fc,
    kronos_fc,
    chronos_fc,
    sentiment_fc,
    baseline_fc,
]

context = {
    "spread_points": 14,
    "atr": 0.0011,
    "atr_norm": 1.0,
    "tick_value": 1.0,
    "commission_per_lot": 7.0,
    "slippage_buffer_points": 5,
    "event_risk": 0.30,
    "regime": "trend",         # trend | mean_revert | chop | high_vol
}

cfg = EnsembleConfig(...)
```

---

## 6.3 Trọng số mặc định

```yaml
weights:
  kronos:    0.35
  timesfm:   0.25
  chronos:   0.20
  sentiment: 0.15
  baseline:  0.05
```

Trọng số này là **starting point**. Tune trong giai đoạn 7 (xem [13-roadmap.md](13-roadmap.md)).

Quy tắc: trọng số tuning chỉ được áp dụng sau khi pass walk-forward. Không refit weight trên test set.

---

## 6.4 Pipeline tính toán

### 6.4.1 Step 1 — Validate input

```python
valid = [f for f in forecasts if f.score is not None and not math.isnan(f.score)]
if len(valid) < min_models:
    return EnsembleResult(direction="HOLD", reason="insufficient_models")
```

### 6.4.2 Step 2 — Re-scale weight nếu thiếu model

```python
active_weights = {f.model_name: w for f, w in zip(valid, weights[...])}
total = sum(active_weights.values())
active_weights = {k: v / total for k, v in active_weights.items()}
```

### 6.4.3 Step 3 — Raw weighted score

```python
raw_score = sum(active_weights[f.model_name] * f.score for f in valid)
```

### 6.4.4 Step 4 — Tính agreement

```python
bullish = sum(1 for f in valid if f.score >  0.15)
bearish = sum(1 for f in valid if f.score < -0.15)
neutral = len(valid) - bullish - bearish
agreement = max(bullish, bearish) / len(valid)
```

### 6.4.5 Step 5 — Cost penalty

```python
spread_cost      = spread_points * point_value / contract_size
commission_cost  = commission_per_lot / lot_notional
slippage_buffer  = slippage_points * point_value / contract_size

cost_penalty = (spread_cost + commission_cost + slippage_buffer) / atr
```

`cost_penalty` được normalize bởi ATR để cùng đơn vị với score.

### 6.4.6 Step 6 — Uncertainty + event penalty

```python
uncertainty_penalty = mean(f.uncertainty_norm for f in valid) * cfg.uncertainty_weight
event_penalty       = context["event_risk"] * cfg.event_weight
```

### 6.4.7 Step 7 — Final score

```python
final_score = raw_score - cost_penalty - uncertainty_penalty - event_penalty
```

### 6.4.8 Step 8 — Rule quyết định

```python
if context["event_risk"] > cfg.max_event_risk:
    return HOLD("event_risk_too_high")

if agreement < cfg.min_agreement:
    return HOLD("low_agreement")

if final_score >  cfg.buy_threshold:
    return BUY(final_score, agreement, reason="passed_buy_threshold")
if final_score < -cfg.sell_threshold:
    return SELL(abs(final_score), agreement, reason="passed_sell_threshold")
return HOLD("score_below_threshold")
```

---

## 6.5 Hard veto rules

Bất kỳ rule nào dưới đây trigger -> trả HOLD ngay, không tính ensemble:

```text
1. Kronos và TimesFM ngược hướng và |kronos.score - timesfm.score| > 0.6
2. event_risk > max_event_risk (mặc định 0.80)
3. spread_points > max_spread_points của symbol
4. atr < min_atr_for_trade (thị trường chết, không có biến động)
5. realized_vol > max_vol_for_trade (chop quá mạnh)
6. forecast edge < cfg.min_edge_to_cost_ratio * cost_penalty
7. > 50% adapter fail trong batch này
```

---

## 6.6 Confidence calibration

```python
confidence = min(1.0, agreement * abs(final_score) / cfg.buy_threshold)
```

Confidence dùng cho:
- Risk manager scale `effective_risk_per_trade`
- Logging và post-trade analysis
- Threshold cho cảnh báo "high-confidence trade"

---

## 6.7 Output schema

```python
@dataclass
class EnsembleResult:
    direction: str           # BUY | SELL | HOLD
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

`components` lưu nguyên bản từng forecast để audit về sau.

---

## 6.8 Regime-aware adjustment (optional)

Nếu phát hiện regime, có thể điều chỉnh weight động:

```python
if regime == "trend":
    weights["kronos"]    *= 1.10
    weights["timesfm"]   *= 1.05
elif regime == "mean_revert":
    weights["chronos"]   *= 1.10
elif regime == "chop":
    weights["baseline"]  *= 0.0   # disable trade
elif regime == "high_vol":
    cfg.buy_threshold *= 1.5
    cfg.sell_threshold *= 1.5
```

Quy tắc: regime detection phải log rõ ràng, có thể disable bằng config.

---

## 6.9 Anti-overfit guardrails

```text
- Không tune weight trên cùng tập dữ liệu dùng để evaluate
- Không thêm rule mới sau khi đã thấy test set
- Walk-forward validation bắt buộc
- Track parity: ensemble vs từng model riêng (xem [10-backtesting.md])
```

---

## 6.10 Pseudo-code đầy đủ

```python
def combine(forecasts, context, cfg) -> EnsembleResult:
    valid = [f for f in forecasts if is_valid(f)]
    if len(valid) < cfg.min_models:
        return hold("insufficient_models", forecasts)

    # 1. weight rescale
    weights = rescale_weights(cfg.weights, [f.model_name for f in valid])

    # 2. raw score
    raw = sum(weights[f.model_name] * f.score for f in valid)

    # 3. agreement
    agreement = compute_agreement(valid, threshold=0.15)

    # 4. penalties
    cost_p   = cost_penalty(context, cfg)
    unc_p    = uncertainty_penalty(valid, cfg)
    event_p  = context["event_risk"] * cfg.event_weight

    final = raw - cost_p - unc_p - event_p

    # 5. veto
    vetoes = run_veto_checks(valid, context, cfg)
    if vetoes:
        return hold("|".join(vetoes), forecasts)

    # 6. threshold
    if agreement < cfg.min_agreement:
        return hold("low_agreement", forecasts)

    if final > cfg.buy_threshold:
        return decision("BUY",  final, agreement, valid, context)
    if final < -cfg.sell_threshold:
        return decision("SELL", abs(final), agreement, valid, context)
    return hold("below_threshold", forecasts)
```

---

## 6.11 Tham số khuyến nghị (starting point)

```yaml
ensemble:
  weights:
    kronos: 0.35
    timesfm: 0.25
    chronos: 0.20
    sentiment: 0.15
    baseline: 0.05

  buy_threshold:    0.25
  sell_threshold:   0.25
  min_agreement:    0.60
  min_models:       3
  max_uncertainty:  0.75
  max_event_risk:   0.80
  uncertainty_weight: 0.30
  event_weight:       0.40
  min_edge_to_cost_ratio: 1.5
```

Kiểm tra lại các giá trị này sau giai đoạn 7 (ensemble backtest).
