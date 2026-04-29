# AI MT5 Multi-Model Trading System — Tài liệu dự án

> Bộ tài liệu triển khai hệ thống AI Trading đa mô hình trên MetaTrader 5
> Kết hợp **TimesFM + Kronos + Chronos + FinGPT/RAG + Agent Orchestration**
> Source blueprint: `ai_mt5_multi_model_deployment_blueprint.md`
> Ngày tạo: 2026-04-29

---

## Mục lục tài liệu

| # | File | Nội dung |
|---|------|----------|
| 00 | [01-overview.md](01-overview.md) | Tổng quan, mục tiêu, scope, nguyên tắc thiết kế |
| 01 | [02-architecture.md](02-architecture.md) | Kiến trúc tổng thể, sơ đồ các tầng, luồng quyết định |
| 02 | [03-tech-stack.md](03-tech-stack.md) | Công nghệ, framework, library, version pinning |
| 03 | [04-models.md](04-models.md) | Vai trò chi tiết của từng mô hình AI |
| 04 | [05-data-pipeline.md](05-data-pipeline.md) | Nguồn dữ liệu, storage, feature engineering |
| 05 | [06-meta-signal.md](06-meta-signal.md) | Ensemble engine, normalization, agreement, cost filter |
| 06 | [07-risk-management.md](07-risk-management.md) | Risk engine, position sizing, kill switch |
| 07 | [08-mt5-execution.md](08-mt5-execution.md) | MT5 connector, executor, Option A vs Option B |
| 08 | [09-agents.md](09-agents.md) | Agent orchestration layer & quyền hạn |
| 09 | [10-backtesting.md](10-backtesting.md) | Backtest framework, walk-forward, metrics |
| 10 | [11-project-structure.md](11-project-structure.md) | Cấu trúc thư mục, module, interface chuẩn |
| 11 | [12-config.md](12-config.md) | Đặc tả file YAML config, env vars |
| 12 | [13-roadmap.md](13-roadmap.md) | Roadmap theo giai đoạn & milestone tuần |
| 13 | [14-deployment.md](14-deployment.md) | Quy trình dry_run → demo → live |
| 14 | [15-monitoring.md](15-monitoring.md) | Logging, dashboard, alert, audit trail |
| 15 | [16-testing-qa.md](16-testing-qa.md) | Chiến lược test (unit / integration / shadow) |
| 16 | [17-security.md](17-security.md) | Secret management, account safety, compliance |
| 17 | [18-pitfalls.md](18-pitfalls.md) | Các bẫy phổ biến & cách phòng tránh |
| 18 | [19-references.md](19-references.md) | Tham khảo chính thức, paper, repo |
| PRD | [prds/README.md](prds/README.md) | Bộ PRD triển khai theo lát cắt milestone |

---

## Đọc theo vai trò

- **Project lead / quant trader**: 01 → 02 → 04 → 06 → 07 → 13
- **ML engineer**: 04 → 05 → 06 → 10 → 11
- **Backend / DevOps**: 03 → 08 → 11 → 14 → 15 → 17
- **Risk / compliance**: 07 → 09 → 14 → 17 → 18
- **Người mới**: đọc theo thứ tự 01 → 19

---

## Triết lý cốt lõi

```text
AI model    -> chỉ tạo forecast/score
Risk manager-> mới quyết định trade size
MT5 executor-> mới gửi lệnh
LLM/Agent   -> KHÔNG được tự gọi market order
```

Mọi quyết định live phải đi qua chuỗi:

```text
forecast -> ensemble -> cost filter -> risk manager -> order_check -> order_send
```

---

## Trạng thái dự án

- [x] Blueprint design (file gốc)
- [x] Documentation set (folder này)
- [ ] Giai đoạn 1: MT5 skeleton
- [ ] Giai đoạn 2: Baseline + logging
- [ ] Giai đoạn 3-6: Model adapters offline
- [ ] Giai đoạn 7: Ensemble backtest
- [ ] Giai đoạn 8: Paper / demo
- [ ] Giai đoạn 9: Live nhỏ

Tham khảo [13-roadmap.md](13-roadmap.md) để xem milestone chi tiết.
