# 19. References

## 19.1 Model chính

### TimesFM (Google Research)
- GitHub: https://github.com/google-research/timesfm
- Blog: https://research.google/blog/a-decoder-only-foundation-model-for-time-series-forecasting/
- Paper: "A decoder-only foundation model for time-series forecasting"

### Kronos
- GitHub: https://github.com/shiyu-coder/Kronos
- Paper: https://arxiv.org/abs/2508.02739
- Lưu ý: pin commit hash, verify reproducibility

### Chronos / Chronos-2 (Amazon)
- GitHub: https://github.com/amazon-science/chronos-forecasting
- Chronos-2 HF: https://huggingface.co/amazon/chronos-2
- Paper Chronos: "Chronos: Learning the Language of Time Series"

### FinGPT / FinBERT
- FinGPT GitHub: https://github.com/AI4Finance-Foundation/FinGPT
- FinGPT site: https://fingpt.io/
- FinBERT (alt): https://huggingface.co/ProsusAI/finbert

---

## 19.2 MT5 integration

- Python MetaTrader5 docs: https://www.mql5.com/en/docs/python_metatrader5
- order_send Python: https://www.mql5.com/en/docs/python_metatrader5/mt5ordersend_py
- order_check Python: https://www.mql5.com/en/docs/python_metatrader5/mt5ordercheck_py
- symbol_info Python: https://www.mql5.com/en/docs/python_metatrader5/mt5symbolinfo_py
- MQL5 Reference: https://www.mql5.com/en/docs

---

## 19.3 Data sources

- OpenBB: https://openbb.co/
- Polygon: https://polygon.io/docs
- Yahoo Finance (yfinance): https://github.com/ranaroussi/yfinance
- FRED: https://fred.stlouisfed.org/
- ForexFactory calendar: https://www.forexfactory.com/calendar
- TradingEconomics API: https://tradingeconomics.com/api/

---

## 19.4 Vector DB / RAG

- Milvus: https://milvus.io/docs
- Zilliz Cloud: https://zilliz.com/cloud
- Qdrant: https://qdrant.tech/
- LangChain RAG: https://python.langchain.com/docs/tutorials/rag/
- LlamaIndex: https://docs.llamaindex.ai/

---

## 19.5 Agent frameworks

- LangGraph: https://langchain-ai.github.io/langgraph/
- CrewAI: https://docs.crewai.com/
- AutoGen: https://microsoft.github.io/autogen/

---

## 19.6 Backtest & quant

- pandas-ta: https://github.com/twopirllc/pandas-ta
- vectorbt: https://vectorbt.dev/
- backtrader: https://www.backtrader.com/
- nautilus_trader: https://nautilustrader.io/

> Lưu ý: dự án này dùng custom backtest engine để tích hợp đầy đủ adapter + risk + cost. Có thể tham khảo các framework trên cho ý tưởng API.

---

## 19.7 Time series & forecasting

- "Forecasting: Principles and Practice" (Hyndman & Athanasopoulos): https://otexts.com/fpp3/
- statsmodels: https://www.statsmodels.org/
- darts: https://unit8co.github.io/darts/

---

## 19.8 Risk & quant trading

- "Advances in Financial Machine Learning" — Marcos Lopez de Prado
- "Active Portfolio Management" — Grinold & Kahn
- "Trading and Exchanges" — Larry Harris
- Kelly criterion, fractional Kelly
- "Quantitative Trading" — Ernest Chan

---

## 19.9 Observability

- Prometheus: https://prometheus.io/docs/
- Grafana: https://grafana.com/docs/
- structlog: https://www.structlog.org/
- OpenTelemetry: https://opentelemetry.io/

---

## 19.10 Security

- OWASP Top 10: https://owasp.org/www-project-top-ten/
- Prompt injection guidance (OWASP for LLM): https://owasp.org/www-project-top-10-for-large-language-model-applications/
- pip-audit: https://pypi.org/project/pip-audit/
- HashiCorp Vault: https://developer.hashicorp.com/vault

---

## 19.11 LangGraph / LLM eval

- LangSmith: https://docs.smith.langchain.com/
- OpenAI evals (open-source patterns): https://github.com/openai/evals

---

## 19.12 Broker docs

> Đặt link broker thực tế khi có. Ví dụ:
- Spread/commission spec
- Symbol contract size
- Trading hours
- Stop level
- Filling mode

---

## 19.13 Python ecosystem

- uv (package manager): https://docs.astral.sh/uv/
- ruff: https://docs.astral.sh/ruff/
- pytest: https://docs.pytest.org/
- hypothesis: https://hypothesis.readthedocs.io/

---

## 19.14 Compliance (tùy quốc gia)

> Tham khảo regulator địa phương:
- US: SEC, CFTC
- EU: ESMA, MiFID II
- UK: FCA
- Singapore: MAS
- Việt Nam: SBV / SSC (CFD/Forex retail bị hạn chế, kiểm tra trạng thái pháp lý trước khi triển khai)

---

## 19.15 Glossary nhanh

| Thuật ngữ | Nghĩa |
|---|---|
| OHLCV | Open/High/Low/Close/Volume |
| ATR | Average True Range |
| SL / TP | Stop Loss / Take Profit |
| RR | Risk-Reward ratio |
| OOS | Out-of-Sample |
| PF | Profit Factor |
| DD | Drawdown |
| RAG | Retrieval Augmented Generation |
| EA | Expert Advisor (MQL5) |
| FOK / IOC | Fill-or-Kill / Immediate-or-Cancel |
| Magic | MT5 magic number để tag order |
| Tick value | giá trị 1 tick cho 1 lot |
| Lot step | bội số tối thiểu khi đặt lot |
| Stop level | khoảng cách tối thiểu giá - SL/TP do broker quy định |
| Walk-forward | phương pháp validate theo time-series |
| Brier score | điểm calibration cho forecast xác suất |

---

## 19.16 Internal docs (file trong dự án)

| File | Topic |
|---|---|
| [README.md](README.md) | Index |
| [01-overview.md](01-overview.md) | Tổng quan, scope |
| [02-architecture.md](02-architecture.md) | Kiến trúc |
| [03-tech-stack.md](03-tech-stack.md) | Công nghệ |
| [04-models.md](04-models.md) | Model adapter |
| [05-data-pipeline.md](05-data-pipeline.md) | Data flow |
| [06-meta-signal.md](06-meta-signal.md) | Ensemble |
| [07-risk-management.md](07-risk-management.md) | Risk |
| [08-mt5-execution.md](08-mt5-execution.md) | MT5 layer |
| [09-agents.md](09-agents.md) | Agents |
| [10-backtesting.md](10-backtesting.md) | Backtest |
| [11-project-structure.md](11-project-structure.md) | Codebase |
| [12-config.md](12-config.md) | Config |
| [13-roadmap.md](13-roadmap.md) | Roadmap |
| [14-deployment.md](14-deployment.md) | Deployment |
| [15-monitoring.md](15-monitoring.md) | Observability |
| [16-testing-qa.md](16-testing-qa.md) | Testing |
| [17-security.md](17-security.md) | Security |
| [18-pitfalls.md](18-pitfalls.md) | Pitfalls |
| [19-references.md](19-references.md) | This file |
