# 03. Tech stack & lựa chọn công nghệ

## 3.1 Ngôn ngữ & runtime

| Lớp | Lựa chọn | Lý do |
|---|---|---|
| Core service | Python 3.11+ | Hệ sinh thái ML, MetaTrader5 package |
| MT5 Terminal | Windows native | MetaQuotes chỉ hỗ trợ Windows full feature |
| EA executor (Option B) | MQL5 | Bắt buộc nếu muốn execution nằm trong terminal |
| Bridge (nếu Option B) | ZeroMQ / REST (FastAPI) / file-based | Tùy yêu cầu latency |

> **Lưu ý**: nếu chạy trên Linux, dùng Wine + MT5, hoặc tách MT5 sang Windows VPS, AI server vẫn Python/Linux.

---

## 3.2 ML / forecasting libraries

| Component | Library | Version target | Ghi chú |
|---|---|---|---|
| TimesFM | `timesfm` (Google Research) | >= latest stable | Yêu cầu JAX hoặc PyTorch |
| Kronos | `Kronos` (shiyu-coder) | repo HEAD | Pin commit hash |
| Chronos / Chronos-2 | `chronos-forecasting` | >= 1.x | HuggingFace `amazon/chronos-2` cho v2 |
| FinGPT / FinBERT | `transformers` + FinGPT weights | >= 4.40 | Có thể thay bằng FinBERT cho tốc độ |
| RAG | `llama-index` hoặc `langchain` | latest stable | Pick 1, không pha trộn |
| Vector DB | Milvus / Zilliz / Qdrant | latest | Milvus cho self-host, Zilliz cho cloud |
| Baseline ML | `scikit-learn`, `lightgbm` | latest | Logistic / GBM cho control |

### Ghim version

```text
- Tạo requirements.txt và pyproject.toml
- Pin major.minor cho mọi ML lib
- Lưu lockfile (uv.lock / poetry.lock / pip-tools)
- Tag commit hash cho Kronos repo
```

---

## 3.3 Data & storage

| Mục đích | Lựa chọn MVP | Lựa chọn production |
|---|---|---|
| OHLCV bars | Parquet + DuckDB | Postgres + TimescaleDB |
| Tick data | Parquet partitioned by symbol/date | TimescaleDB hypertable |
| Predictions | SQLite | Postgres |
| News/documents | SQLite | Postgres + S3 |
| Embeddings | Milvus standalone | Milvus / Zilliz cluster |
| Cache | dict in-memory | Redis |

### Schema tham khảo

```sql
-- bars
CREATE TABLE bars (
  symbol      TEXT,
  timeframe   TEXT,
  ts          TIMESTAMPTZ,
  open        DOUBLE PRECISION,
  high        DOUBLE PRECISION,
  low         DOUBLE PRECISION,
  close       DOUBLE PRECISION,
  tick_volume BIGINT,
  spread      INTEGER,
  PRIMARY KEY (symbol, timeframe, ts)
);

-- forecasts
CREATE TABLE forecasts (
  id            BIGSERIAL PRIMARY KEY,
  ts            TIMESTAMPTZ,
  symbol        TEXT,
  timeframe     TEXT,
  model_name    TEXT,
  horizon       INTEGER,
  direction     TEXT,
  expected_return DOUBLE PRECISION,
  uncertainty   DOUBLE PRECISION,
  raw_score     DOUBLE PRECISION,
  score         DOUBLE PRECISION,
  confidence    DOUBLE PRECISION,
  reason        TEXT,
  metadata      JSONB
);

-- signals
CREATE TABLE signals (
  id            BIGSERIAL PRIMARY KEY,
  ts            TIMESTAMPTZ,
  symbol        TEXT,
  timeframe     TEXT,
  final_score   DOUBLE PRECISION,
  agreement     DOUBLE PRECISION,
  signal        TEXT,           -- BUY/SELL/HOLD
  approved      BOOLEAN,
  reason        TEXT,
  ensemble_meta JSONB
);

-- trades
CREATE TABLE trades (
  id            BIGSERIAL PRIMARY KEY,
  signal_id     BIGINT REFERENCES signals(id),
  ts_request    TIMESTAMPTZ,
  ts_filled     TIMESTAMPTZ,
  symbol        TEXT,
  side          TEXT,
  volume        DOUBLE PRECISION,
  entry_price   DOUBLE PRECISION,
  sl            DOUBLE PRECISION,
  tp            DOUBLE PRECISION,
  exit_price    DOUBLE PRECISION,
  pnl           DOUBLE PRECISION,
  status        TEXT,
  mt5_ticket    BIGINT,
  comment       TEXT
);
```

---

## 3.4 MT5 integration

| Tùy chọn | Library | Trường hợp dùng |
|---|---|---|
| Option A | `MetaTrader5` (PyPI) | MVP, nhanh |
| Option B | MQL5 EA + Python service | Production, low-latency |
| Bridge protocol | ZeroMQ / REST / named pipe | ZMQ cho latency thấp |

Tham khảo:
- https://www.mql5.com/en/docs/python_metatrader5
- https://www.mql5.com/en/docs/python_metatrader5/mt5ordersend_py

---

## 3.5 Orchestration & scheduling

| Mục đích | MVP | Production |
|---|---|---|
| Scheduling | `cron` / Windows Task Scheduler | `APScheduler`, `Prefect`, `Airflow` |
| Job queue | Không cần | Celery + Redis / Prefect |
| Process supervisor | systemd / nssm | Kubernetes / Nomad |

---

## 3.6 Agent framework

Lựa chọn **một** trong các framework sau (không pha trộn):

```text
- LangGraph    - rõ ràng về graph state, dễ audit
- CrewAI       - đơn giản, role-based
- AutoGen      - multi-agent conversation
- LlamaIndex Agents - tốt cho RAG-heavy workflow
```

Khuyến nghị: **LangGraph** vì state machine rõ ràng và dễ test deterministic.

---

## 3.7 Observability

| Lớp | Tool |
|---|---|
| Logging | `structlog` JSONL → file + stdout |
| Metrics | Prometheus (production) / CSV (MVP) |
| Dashboard | Streamlit (MVP) / Grafana (production) |
| Alert | Telegram bot / email / PagerDuty |
| Tracing | OpenTelemetry (optional, production) |

---

## 3.8 Testing

| Loại | Tool |
|---|---|
| Unit | pytest |
| Property-based | hypothesis (cho risk engine, normalizer) |
| Integration | pytest + MT5 demo |
| Backtest | custom engine (xem [10-backtesting.md](10-backtesting.md)) |
| Load | locust (chỉ Option B với REST bridge) |

---

## 3.9 Security & secrets

| Mục | Tool |
|---|---|
| Secret store | OS keyring / .env + git-ignored / Vault |
| Credentials MT5 | Env var, không hard-code |
| API keys (news, OpenAI, etc.) | `.env` + dotenv, mask trong log |
| Audit log | append-only, không cho phép xóa |

Chi tiết xem [17-security.md](17-security.md).

---

## 3.10 CI/CD

```text
- Repo: Git (GitHub/GitLab/self-host)
- Lint: ruff
- Format: black
- Type check: mypy / pyright (cho file boundary, không bắt buộc full)
- Test: pytest
- CI: GitHub Actions / GitLab CI
- Pre-commit hooks: ruff + black + mypy (file mức risk)
- Deployment: image Docker (cho AI server) hoặc rsync + systemd
```

---

## 3.11 Hardware tham chiếu

### MVP (chỉ inference offline)

```text
CPU: 8 core
RAM: 16-32 GB
GPU: GTX/RTX (8GB+) cho TimesFM/Kronos local
Disk: 200 GB SSD (parquet OHLCV nhiều năm)
```

### Production

```text
MT5 host: Windows VPS, 2-4 vCPU, 8 GB RAM, gần broker server
AI server: GPU machine (A10/A100/RTX 4090) nếu chạy local
DB: managed Postgres + Timescale
```

Nếu dùng API host (HuggingFace Inference / OpenAI / Anthropic), GPU local có thể bỏ — đánh đổi latency và privacy.

---

## 3.12 Bill of materials

```text
runtime: python:3.11-slim
ml:
  - torch
  - jax (nếu TimesFM JAX backend)
  - transformers
  - timesfm
  - chronos-forecasting
  - kronos (git+...)
  - lightgbm
  - scikit-learn

data:
  - pandas, numpy, pyarrow, duckdb
  - sqlalchemy, psycopg2-binary (production)
  - pymilvus (nếu Milvus)

mt5:
  - MetaTrader5
  - pytz

orchestration:
  - apscheduler
  - langgraph
  - llama-index (nếu RAG)

observability:
  - structlog
  - prometheus-client
  - streamlit (MVP)

testing:
  - pytest, pytest-cov, hypothesis
```
