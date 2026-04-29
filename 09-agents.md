# 09. Agent orchestration layer

## 9.1 Vai trò agent layer

Agent layer **không** trực tiếp trade. Nó là tầng điều phối, audit, báo cáo, gọi tool có sẵn. Agent giúp:

- Chia nhỏ workflow thành các bước có thể inspect
- Cung cấp lý do bằng ngôn ngữ tự nhiên cho mỗi quyết định
- Tự động tạo báo cáo định kỳ
- Chuyển hướng/gọi đúng adapter khi điều kiện thay đổi

Agent **không** được phép:

```text
- Gọi mt5.order_send
- Sửa risk config
- Bypass risk_manager
- Tự tăng lot vì "cảm thấy chắc"
- Lưu state ngoài hệ thống audit chính thức
```

---

## 9.2 Danh sách agent

| Agent | Trách nhiệm | Tools được phép gọi |
|---|---|---|
| **DataAgent** | Đảm bảo data tươi, đầy đủ | `fetch_bars`, `fetch_news`, `health_check` |
| **NewsAgent** | Tóm tắt news, gọi RAG, đánh giá event | `retrieve_news`, `embed`, `fingpt_predict` |
| **QuantAgent** | Chạy adapter forecast | `timesfm_predict`, `kronos_predict`, `chronos_predict`, `baseline_predict` |
| **EnsembleAgent** | Gọi meta-signal engine | `combine`, `regime_detect` |
| **RiskAgent** | Gọi risk_manager (read-only check) | `risk_evaluate`, `account_info`, `positions_get` |
| **AuditAgent** | Ghi reason, lưu audit trail | `log_event`, `persist_audit` |
| **ReportAgent** | Báo cáo daily/weekly | `query_db`, `render_report`, `send_telegram` |

---

## 9.3 Tools whitelist

Mỗi agent được cấu hình tool whitelist. Vi phạm = hard error.

```yaml
agents:
  DataAgent:
    allowed_tools: [fetch_bars, fetch_ticks, fetch_news, health_check]

  NewsAgent:
    allowed_tools: [retrieve_news, embed, fingpt_predict]

  QuantAgent:
    allowed_tools: [timesfm_predict, kronos_predict, chronos_predict, baseline_predict]

  EnsembleAgent:
    allowed_tools: [combine, regime_detect]

  RiskAgent:
    allowed_tools: [risk_evaluate, account_info, positions_get, mt5_order_check]

  AuditAgent:
    allowed_tools: [log_event, persist_audit, render_reason]

  ReportAgent:
    allowed_tools: [query_db, render_report, send_telegram, send_email]
```

`mt5_order_send` **không xuất hiện** trong bất kỳ allowlist nào của agent. Chỉ executor module gọi nó (xem [08-mt5-execution.md](08-mt5-execution.md)).

---

## 9.4 Workflow chính (state graph)

Khuyến nghị dùng **LangGraph** vì state machine rõ ràng:

```text
              ┌────────────┐
              │   START    │
              └─────┬──────┘
                    ▼
              ┌────────────┐
              │ DataAgent  │   - kiểm tra freshness
              └─────┬──────┘   - nếu stale -> END(skip)
                    ▼
        ┌───────────┴────────────┐
        ▼                        ▼
  ┌───────────┐            ┌───────────┐
  │NewsAgent  │ (parallel) │QuantAgent │
  └─────┬─────┘            └─────┬─────┘
        └───────────┬────────────┘
                    ▼
              ┌─────────────┐
              │EnsembleAgent│
              └─────┬───────┘
                    ▼
              ┌─────────────┐
              │ RiskAgent   │
              └─────┬───────┘
                    ▼
              ┌─────────────┐
              │ AuditAgent  │
              └─────┬───────┘
                    ▼
              ┌─────────────┐
              │  EXECUTOR   │   <-- không phải agent, là module deterministic
              └─────────────┘
```

EnsembleAgent và RiskAgent chỉ gọi engine deterministic, không tự sáng tạo logic. Chúng tồn tại để **ghi reason** và **format**.

---

## 9.5 LangGraph state schema

```python
@dataclass
class TradingState:
    ts: datetime
    symbol: str
    timeframe: str
    bars: pd.DataFrame | None = None
    news_ctx: list | None = None

    forecasts: list[ModelForecast] = field(default_factory=list)
    ensemble: EnsembleResult | None = None
    risk: RiskDecision | None = None

    errors: list[str] = field(default_factory=list)
    audit: list[dict] = field(default_factory=list)
    final_action: str = "HOLD"
```

Mọi agent đọc/ghi vào `TradingState`. Không có biến global.

---

## 9.6 Reason rendering

AuditAgent chịu trách nhiệm sinh reason có cấu trúc, **không phải tự do**:

```python
{
  "schema_version": "1",
  "decision": "BUY",
  "drivers": [
    {"name": "kronos", "score": 0.55, "weight": 0.35, "contrib": 0.193},
    {"name": "timesfm", "score": 0.43, "weight": 0.25, "contrib": 0.108}
  ],
  "penalties": {"cost": 0.04, "uncertainty": 0.03, "event": 0.12},
  "agreement": 0.80,
  "final_score": 0.37,
  "narrative": "Kronos và TimesFM đồng thuận BUY. Sentiment trung tính. CPI cách 35 phút nên giảm size."
}
```

`narrative` có thể do LLM viết, nhưng các trường numeric **phải** từ ensemble engine.

---

## 9.7 LLM safety layer

Khi LLM tham gia (NewsAgent, AuditAgent, ReportAgent):

```text
- Output schema enforced (pydantic / json schema)
- Refuse mọi yêu cầu thay đổi config / gọi order_send
- Refuse "nhân danh user" để bypass risk
- Token budget hard limit
- Timeout 5-10s, fallback rule-based nếu fail
- Log full prompt + response để audit
```

Prompt template phải có guardrail:

```text
You are an audit narrator. You MUST NOT recommend trade size or call any order tool.
You MUST output JSON matching the schema. If you are uncertain, return narrative="".
```

---

## 9.8 Multi-agent vs single-pipeline

Không bắt buộc dùng agent framework. Thay thế đơn giản hơn:

```python
def tick(symbol, timeframe, ts):
    bars       = data.fetch(symbol, timeframe)
    news_ctx   = news.retrieve(symbol, ts)
    forecasts  = run_adapters(bars, news_ctx)
    ensemble   = ensemble_engine.combine(forecasts, ctx, cfg)
    risk_dec   = risk_manager.evaluate(ensemble, account, market, cfg)
    audit.log(forecasts, ensemble, risk_dec)
    if risk_dec.approved:
        executor.submit(risk_dec)
```

**Khuyến nghị MVP**: dùng pipeline thẳng. Chỉ chuyển sang agent framework khi cần báo cáo/giải thích phức tạp.

---

## 9.9 Khi nào agent thật sự đáng giá

Agent layer xứng đáng khi:

```text
- Cần báo cáo NL hàng ngày cho stakeholder không biết code
- Cần routing có điều kiện (vd: weekend chỉ chạy DataAgent + Report)
- Workflow nhánh phức tạp (Earnings Day vs Normal Day)
- Có nhiều human-in-the-loop checkpoint
```

Nếu không có nhu cầu trên -> pipeline thẳng đủ và ít rủi ro hơn.

---

## 9.10 Test agent

```text
- Mock tool: mỗi agent unit test với fake adapter
- Deterministic seed cho LLM call (temperature=0, hoặc dùng cassette/replay)
- Refuse test: prompt cố ý yêu cầu order_send -> phải bị reject
- Output schema validation
- E2E: 1 ngày dữ liệu replay -> so sánh kết quả với pipeline thẳng
```

---

## 9.11 Quy tắc bất di bất dịch

```text
1. Agent không gọi order_send.
2. Agent không sửa config runtime.
3. Agent không bypass risk_manager.
4. Mọi tool của agent phải đọc-only HOẶC ghi vào audit-only store.
5. Mọi output dùng cho quyết định trade phải có schema cứng.
6. Nếu LLM fail -> fallback rule-based, không "đoán".
```
