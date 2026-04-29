# 05. Data pipeline

## 5.1 Nguồn dữ liệu

| Loại | Nguồn chính | Backup | Tần suất |
|---|---|---|---|
| OHLCV bars | MT5 `copy_rates_*` | OpenBB / Polygon / Yahoo | mỗi close-bar |
| Tick | MT5 `copy_ticks_range` | broker FIX (production) | streaming |
| Spread / symbol info | MT5 `symbol_info` | — | cache 1 phút |
| Account info | MT5 `account_info` | — | trước mỗi quyết định |
| Macro calendar | ForexFactory / TradingEconomics API | manual CSV | hàng ngày |
| News | RSS / NewsAPI / Bloomberg | scrape thận trọng | 5-15 phút |
| Cross-asset (DXY, VIX, US10Y) | Yahoo / FRED / OpenBB | broker symbol khác | đồng bộ với target TF |

> Luôn có **fallback** cho nguồn primary. Nếu fail, log + degrade gracefully.

---

## 5.2 MT5 data fetch

### 5.2.1 Bars

```python
import MetaTrader5 as mt5
import pandas as pd

def fetch_bars(symbol: str, timeframe: int, n: int = 600) -> pd.DataFrame:
    bars = mt5.copy_rates_from_pos(symbol, timeframe, 0, n)
    if bars is None or len(bars) == 0:
        raise RuntimeError(f"No bars for {symbol}")
    df = pd.DataFrame(bars)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    return df

def closed_bars_only(df: pd.DataFrame) -> pd.DataFrame:
    return df.iloc[:-1].copy()
```

### 5.2.2 Tick (chỉ khi cần micro-structure)

```python
def fetch_ticks(symbol: str, ts_from, ts_to) -> pd.DataFrame:
    ticks = mt5.copy_ticks_range(symbol, ts_from, ts_to, mt5.COPY_TICKS_ALL)
    return pd.DataFrame(ticks)
```

### 5.2.3 Symbol info

```python
def fetch_symbol_info(symbol: str):
    info = mt5.symbol_info(symbol)
    if info is None or not info.visible:
        mt5.symbol_select(symbol, True)
        info = mt5.symbol_info(symbol)
    return info
```

---

## 5.3 Storage layout

```text
data/
  bars/
    EURUSD/
      M15/
        2024.parquet
        2025.parquet
        2026.parquet
  ticks/
    EURUSD/
      2026-04-29.parquet
  documents/
    news/
      2026-04-29/
        <doc_id>.json
  embeddings/
    milvus_collection/
  predictions/
    forecasts.sqlite
    signals.sqlite
    trades.sqlite
```

### Parquet schema (bars)

```text
columns:
  time:        timestamp[ns, UTC]
  open:        double
  high:        double
  low:         double
  close:       double
  tick_volume: int64
  spread:      int32
  real_volume: int64 (nếu broker hỗ trợ)
partition_by: [symbol, timeframe, year]
```

---

## 5.4 Feature engineering

### 5.4.1 Features cơ bản

```python
def add_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["log_return"]   = (df["close"] / df["close"].shift(1)).apply(np.log)
    df["return"]       = df["close"].pct_change()
    df["range"]        = df["high"] - df["low"]
    df["body"]         = (df["close"] - df["open"]).abs()
    df["atr_14"]       = compute_atr(df, n=14)
    df["realized_vol"] = df["log_return"].rolling(32).std()
    df["volume_z"]     = (df["tick_volume"] - df["tick_volume"].rolling(96).mean()) \
                          / df["tick_volume"].rolling(96).std()
    df["spread_norm"]  = df["spread"] / df["atr_14"]
    return df
```

### 5.4.2 Anti-leak rules

```text
- Mọi feature dùng tại bar t CHỈ được tính từ dữ liệu <= t-1
- Không dùng future return làm feature
- Khi backtest, slice df bằng iloc[:t] trước khi forecast
- closed_bar_only=true mặc định
```

### 5.4.3 Normalization theo symbol

Mỗi symbol có scale khác nhau (EURUSD 1.08 vs XAUUSD 2300). Luôn dùng **return / log-return / volatility-normalized** cho input model, không raw price.

---

## 5.5 News ingestion

### 5.5.1 Pipeline

```text
1. Fetch RSS / API mỗi 5-15 phút
2. Dedupe theo (source, title_hash)
3. Persist raw JSON vào documents/news/
4. Embed (OpenAI / sentence-transformers) -> Milvus
5. Lưu metadata: ts, source, symbols, language
```

### 5.5.2 RAG retrieval cho FinGPT

```python
def retrieve_news_context(symbol, ts, lookback_hours=24, top_k=10):
    query = build_symbol_query(symbol)
    embed = embedder.encode(query)
    candidates = vector_db.search(embed, filter={
        "ts__gte": ts - timedelta(hours=lookback_hours),
        "symbols__contains": symbol,
    }, top_k=top_k * 3)
    # rerank theo recency + relevance
    return rerank(candidates, ts)[:top_k]
```

### 5.5.3 Sentiment weight decay

```python
def time_decay_weight(doc_ts, now, half_life_hours=12):
    age_h = (now - doc_ts).total_seconds() / 3600
    return 0.5 ** (age_h / half_life_hours)
```

---

## 5.6 Macro calendar

```python
{
    "ts": "2026-04-30T12:30:00Z",
    "event": "US CPI YoY",
    "currency": "USD",
    "impact": "high",   # low|medium|high
    "actual": null,
    "forecast": 3.1,
    "previous": 3.2,
}
```

Quy tắc no-trade window:

```yaml
news_window:
  high_impact:    [-30, +30]   # phút trước/sau
  medium_impact:  [-10, +15]
```

---

## 5.7 Cross-asset features (cho Chronos covariates)

```text
DXY     -> ICE U.S. Dollar Index
US10Y   -> 10Y Treasury yield
VIX     -> CBOE volatility
SPX     -> S&P 500
WTI/Brent -> oil
GOLD    -> spot
```

Cần đồng bộ timestamp với target. Forward-fill cẩn thận, không gây leak.

---

## 5.8 Scheduling & freshness SLO

| Pipeline | Tần suất | SLO độ trễ |
|---|---|---|
| MT5 bars fetch | mỗi close-bar | <= 5s |
| News RSS pull | 5-15 phút | <= 2 phút trễ |
| News embedding | best-effort | <= 5 phút |
| Macro calendar | mỗi giờ | <= 5 phút |
| Cross-asset | mỗi close-bar M15 | <= 30s |

Nếu vi phạm SLO -> alert; degrade mode tự động bỏ feature/sentiment.

---

## 5.9 Data quality checks

```text
- Missing bar detection (timeline continuity)
- Spread sanity (spread > 100*median -> cờ broker issue)
- Outlier detection: log-return > 6 sigma -> flag, không drop
- Volume = 0 cảnh báo (broker symbol mới hoặc weekend)
- Tick gap khi rollover futures
```

Mọi check fail phải log và (nếu nghiêm trọng) đẩy vào kill_switch_pre_check.

---

## 5.10 Backfill & replay

```text
- Backfill nến lịch sử ban đầu: mt5.copy_rates_range trên dải năm
- Replay backtest: load parquet -> stream theo timestamp tăng dần
- Replay phải dùng giá close bar và spread tại thời điểm đó
- Không được nhìn forward
```

Chi tiết backtest: xem [10-backtesting.md](10-backtesting.md).
