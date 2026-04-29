# 10. Backtesting framework

## 10.1 Nguyên tắc

```text
- Closed-bar only: không dùng nến đang chạy
- No look-ahead: feature tại bar t chỉ dùng dữ liệu <= t-1
- Realistic cost: spread + commission + slippage + swap
- Walk-forward: train/val/test theo thời gian, không random split
- Out-of-sample mandatory: số liệu thật chỉ tính trên OOS
- Reproducibility: seed cố định, lưu config + commit hash
```

Nếu vi phạm bất kỳ điểm nào, kết quả backtest **không có giá trị**.

---

## 10.2 Cấu trúc backtest engine

```text
src/backtest/
  engine.py          - main loop, replay bar by bar
  cost_model.py      - spread/commission/slippage simulation
  metrics.py         - PnL stats, Sharpe, drawdown
  walk_forward.py    - split logic, refit weights
  reports.py         - HTML / Markdown / CSV outputs
  fixtures/
    broker_xauusd.yaml
    broker_eurusd.yaml
```

---

## 10.3 Replay loop

```python
def backtest(df, cfg, adapters):
    state = init_state()
    history = []

    for i in range(cfg.warmup, len(df)):
        window  = df.iloc[:i]                 # closed bars only
        ts      = df.iloc[i]["time"]
        market  = market_snapshot(window, cfg)

        forecasts = run_adapters(adapters, window, news=load_news(ts, cfg))
        ensemble  = ensemble_engine.combine(forecasts, market, cfg.ensemble)

        # Risk uses simulated account (not real MT5)
        account = state.account_snapshot()
        risk    = risk_manager.evaluate(ensemble, account, market, cfg.risk)

        if risk.approved:
            entry_price = simulate_entry(df.iloc[i], risk, cost_model)
            state.open_position(entry_price, risk, ts)

        state.update_open_positions(df.iloc[i], cost_model)
        history.append(state.snapshot())

    return BacktestResult(history=history)
```

---

## 10.4 Cost model

### 10.4.1 Spread

```python
def simulated_spread(bar, cfg):
    base_spread = cfg.broker.spread_points[symbol]
    # tùy chọn: scale theo volatility/session
    if bar["session"] in {"asia_lunch", "rollover"}:
        return base_spread * 1.5
    return base_spread
```

Khi có dữ liệu spread thực tế từ MT5 ticks, ưu tiên dùng dữ liệu thật, không simulate.

### 10.4.2 Commission

```python
commission_per_lot_per_side = cfg.broker.commission_per_lot   # USD
total_commission = volume * commission_per_lot_per_side * 2
```

### 10.4.3 Slippage

```python
slippage_buffer_points = cfg.broker.slippage_buffer_points
slippage_price = slippage_buffer_points * point
```

Áp dụng:

```python
fill_price = mid_price + (spread/2 + slippage_price) * sign(side)
```

### 10.4.4 Swap (overnight)

```python
if position_open_overnight:
    swap_charge = volume * cfg.broker.swap[side] * nights_held
```

Cần fetch swap thực tế từ `mt5.symbol_info` và lưu vào fixture.

---

## 10.5 Walk-forward split

```text
| --- train --- | --- val --- | --- test (OOS) --- |
|     6 mo      |    1 mo     |        1 mo        |

Mỗi step trượt 1 tháng:
  Window 1: train = M01-M06, val = M07,    test = M08
  Window 2: train = M02-M07, val = M08,    test = M09
  Window 3: train = M03-M08, val = M09,    test = M10
  ...
```

Mỗi window:
1. Tune weight ensemble trên `train + val`
2. Lock weight
3. Evaluate trên `test`
4. Lưu metrics + weight đã chọn

OOS metric = stitch tất cả `test` window.

---

## 10.6 Metrics tối thiểu

```text
- total_trades
- win_rate
- average_win, average_loss
- profit_factor = sum_wins / |sum_losses|
- expectancy = (avg_win * win_rate) - (avg_loss * (1 - win_rate))
- max_drawdown_pct
- max_drawdown_duration_days
- sharpe_ratio (annualized)
- sortino_ratio
- calmar_ratio
- average_R = avg_pnl / avg_risk
- largest_loss
- consecutive_losses_max
- exposure_time_pct
- turnover
- profit_after_costs
```

Tất cả phải tính sau cost.

---

## 10.7 Comparisons bắt buộc

Backtest phải so sánh **ensemble** với:

```text
1. Kronos only
2. TimesFM only
3. Chronos only
4. Sentiment only
5. Baseline (SMA/ATR/LightGBM)
6. No-trade (buy & hold cho stock CFD)
```

Nếu ensemble **không** vượt trội >= 1 trong các baseline về risk-adjusted return, **không go live**.

---

## 10.8 Stress tests

```text
- Doubled spread (broker tệ)
- Slippage 2x buffer
- Commission +50%
- Bỏ FinGPT (sentiment unavailable)
- Bỏ Chronos
- 1 model raise exception 10% thời gian
- Latency model inference 2-5s (trễ 1 nến)
- News window block 30% thời gian
```

Mỗi stress test cho ra report riêng. Nếu drawdown > 2x baseline drawdown -> chiến lược fragile.

---

## 10.9 Anti-overfit guardrails

```text
- Tối đa 3 vòng tune weight cho mỗi window
- Không thêm rule mới sau khi đã thấy test metrics
- Track number of "fits" và lưu vào report
- Nếu sharpe in-sample > 2x sharpe OOS -> nghi overfit
- Cross-symbol validation: weight tune trên EURUSD test trên XAUUSD (degraded nhưng không sụp hoàn toàn)
```

---

## 10.10 Backtest report

```markdown
# Backtest Report — EURUSD M15 — 2024-01..2026-04

**Window**: walk-forward 12 windows, 1mo OOS each
**Cost model**: broker fixture `eurusd_broker_a.yaml`
**Commit**: a1b2c3d
**Config**: configs/backtest_v1.yaml

## OOS metrics (stitched)
- Trades: 412
- Win rate: 58.4%
- Profit factor: 1.42
- Max DD: 6.1%
- Sharpe: 1.18
- Calmar: 1.93

## vs baselines
| Strategy | Trades | PF | DD | Sharpe |
|----------|--------|------|------|--------|
| Ensemble | 412 | 1.42 | 6.1% | 1.18 |
| Kronos   | 510 | 1.21 | 8.3% | 0.84 |
| TimesFM  | 380 | 1.05 | 11%  | 0.31 |
| Baseline | 600 | 1.02 | 14%  | 0.10 |

## Weight per window
[plot weight evolution]

## Equity curve
[plot equity vs baselines]

## Decision attribution
[breakdown by driver]
```

Lưu HTML/PDF + commit vào repo `reports/`.

---

## 10.11 Live shadow mode

Trước khi go live:

```text
- Chạy pipeline trên live data, KHÔNG đặt lệnh
- Lưu mọi forecast/signal vào DB
- So sánh signal với hành vi thị trường thực tế
- Chạy ít nhất 2-4 tuần
- So sánh với backtest cùng giai đoạn
```

Nếu shadow chênh lớn so với backtest -> debug pipeline trước khi live.

---

## 10.12 Reproducibility

Mọi backtest report phải kèm:

```yaml
backtest_meta:
  commit: "a1b2c3d"
  config_path: "configs/backtest_v1.yaml"
  data_snapshot:
    bars_md5: "..."
    news_md5: "..."
  python: "3.11.x"
  packages_lock: "uv.lock"
  seed: 42
  ts_run: "2026-04-29T10:00:00Z"
```

Nếu không reproduce được, kết quả không được dùng để ra quyết định go-live.
