# 16. Testing & QA strategy

## 16.1 Tổng quan các tầng test

| Tầng | Tool | Mục đích | Bắt buộc trước |
|---|---|---|---|
| Unit | pytest | logic thuần | merge PR |
| Property | hypothesis | invariant của risk/normalizer | merge module risk/signal |
| Integration | pytest + MT5 demo | giao tiếp với MT5 | promote demo |
| Backtest | custom engine | hiệu quả chiến lược | promote demo |
| Shadow | live paper | kiểm chứng trên live data | promote live |
| Chaos | scripts | test fail mode | promote live |

---

## 16.2 Unit tests

Cấu trúc:

```text
tests/unit/
  test_normalizer.py
  test_ensemble.py
  test_cost_model.py
  test_risk_manager.py
  test_position_sizing.py
  test_kill_switch.py
  test_news_loader.py
  test_feature_builder.py
  test_executor_request_builder.py
```

Mục tiêu coverage:
```text
- signal/ và risk/: >= 90%
- mt5/executor request builder: >= 80%
- models/ adapter (logic ngoài inference): >= 70%
```

---

## 16.3 Property-based tests (hypothesis)

Quan trọng cho risk engine vì không gian input lớn:

```python
from hypothesis import given, strategies as st

@given(
    equity=st.floats(min_value=100, max_value=1_000_000),
    confidence=st.floats(min_value=0, max_value=1),
    agreement=st.floats(min_value=0, max_value=1),
    atr=st.floats(min_value=1e-6, max_value=10),
    spread=st.integers(min_value=0, max_value=500),
)
def test_position_size_invariants(equity, confidence, agreement, atr, spread):
    decision = risk_manager.evaluate(...)
    if decision.approved:
        # Invariant
        assert decision.volume >= broker.volume_min
        assert decision.volume <= broker.volume_max
        money_at_risk = decision.volume * loss_per_lot(...)
        assert money_at_risk <= equity * cfg.max_risk_per_trade
        assert decision.sl is not None and decision.tp is not None
        assert validate_rr(decision.sl, decision.tp, decision.side)
```

---

## 16.4 Integration tests

### MT5 connection (cần demo account)

```python
@pytest.mark.integration
def test_mt5_connect_fetch_bars():
    with mt5_session(cfg_demo) as mt:
        bars = market_data.fetch_bars("EURUSD", mt5.TIMEFRAME_M15, 100)
        assert len(bars) == 100
        assert bars["time"].is_monotonic_increasing
```

### order_check trên demo

```python
@pytest.mark.integration
def test_order_check_pass_on_demo():
    req = build_test_request("EURUSD", "BUY", volume=0.01)
    check = mt5.order_check(req)
    assert check.retcode == mt5.TRADE_RETCODE_DONE
```

### E2E pipeline (mock model + real MT5 demo)

```python
@pytest.mark.integration
def test_pipeline_e2e_dry_run():
    cfg = load_test_cfg(dry_run=True)
    runner.tick(adapters=mock_adapters(), executor=executor, storage=tmp_storage, cfg=cfg)
    assert tmp_storage.has_signal()
    assert not tmp_storage.has_real_order()
```

---

## 16.5 Backtest as test

Backtest engine cũng phải có test:

```text
- Replay với fixture deterministic -> kết quả không đổi giữa các lần chạy
- Cost model test: spread/commission/swap đúng
- Walk-forward split không leak
- Metric tính đúng (so với scipy/numpy reference)
```

---

## 16.6 Shadow testing

Trước khi go live:

```text
- Pipeline chạy live trên demo
- Mọi forecast, signal, risk decision lưu DB
- KHÔNG đặt lệnh
- Sau 2-4 tuần:
    - So sánh với backtest cùng kỳ
    - Sharpe live shadow >= 0.7 * Sharpe backtest
    - DD shadow trong limit
```

Nếu shadow tệ hơn nhiều backtest -> debug data/news pipeline.

---

## 16.7 Chaos tests

Mô phỏng lỗi để verify graceful degradation:

```text
- MT5 disconnect 30s -> reconnect tự động
- Adapter raise exception -> ensemble re-scale weight, không crash
- News pipeline trả empty -> sentiment_weight = 0, vẫn trade
- DB lock -> retry với backoff, sau N retry alert
- Kill switch file xuất hiện -> mọi quyết định reject
- Disk full -> alert critical, dừng append log
- Clock drift > 5s -> stop trade
- Adapter latency 10s -> coi như fail, không trade nến đó
```

Script trong `scripts/chaos/`:

```text
chaos_disconnect_mt5.sh
chaos_kill_news.sh
chaos_fill_disk.sh
chaos_kill_switch.sh
```

---

## 16.8 Data tests

Sanity checks chạy hàng ngày:

```text
- Không có gap bar quá 1 nến trong session
- Spread median trong khoảng kỳ vọng
- Volume > 0
- News có ít nhất N documents/ngày
- Embeddings count tăng monotonic
```

Fail -> WARN alert, tự động skip trade trên symbol bị ảnh hưởng.

---

## 16.9 Model tests

```text
- Adapter conform schema (dataclass match)
- Adapter trả NaN-safe khi data ngắn
- Adapter raise rõ ràng khi input thiếu cột
- Inference output deterministic (seed cố định)
- Fast smoke test cho mỗi adapter (~1s) trong CI
- Heavy test: 1 tháng dữ liệu, chạy nightly
```

---

## 16.10 Regression suite

Mỗi commit chạy CI:

```text
[CI lint]
- ruff
- black --check
- mypy (file boundary)

[CI test]
- pytest unit (fast)
- pytest property (fast)
- pytest integration (skipped, cần demo account)
- backtest smoke (fixture nhỏ)

[CI build]
- docker build
- artifact upload
```

Trước release:
```text
- pytest integration (manual với demo)
- backtest full suite (nightly)
- chaos tests (weekly)
```

---

## 16.11 Test data

```text
tests/fixtures/
  bars_eurusd_m15_2024.parquet      (1 năm sample)
  news_2024.json                    (news mẫu)
  account_demo.json                 (account snapshot)
  broker_eurusd.yaml                (cost fixture)
  ensemble_cases.yaml               (test case ensemble: input -> expected)
```

Cập nhật fixture khi:
- Schema thay đổi
- Broker fee thay đổi (snapshot)
- Có dữ liệu market mới quan trọng (CPI day, flash crash, ...)

---

## 16.12 Tieu chí ready-to-merge

PR chỉ merge khi:

```text
[ ] CI xanh
[ ] Coverage không giảm
[ ] Code review >= 1 approve (>= 2 cho file risk/)
[ ] Backtest re-run nếu thay đổi signal/risk
[ ] Changelog cập nhật nếu thay đổi behavior
```

PR thay đổi `config/risk.yaml` hoặc `signal/ensemble.py`:
```text
[ ] Risk officer approve
[ ] Backtest report mới đính kèm
[ ] So sánh với backtest cũ
```
