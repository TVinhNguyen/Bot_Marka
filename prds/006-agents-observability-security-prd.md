---
title: PRD 006 - Agent Orchestration, Observability, Security, and Governance
labels: [needs-triage]
status: draft
created: 2026-04-29
source_docs: [02-architecture.md, 03-tech-stack.md, 09-agents.md, 12-config.md, 14-deployment.md, 15-monitoring.md, 16-testing-qa.md, 17-security.md, 18-pitfalls.md]
---

# PRD 006 - Agent Orchestration, Observability, Security, and Governance

## Problem Statement

The system needs clear audit, monitoring, reporting, and security controls. The documents also define an optional agent layer, but agents can introduce risk if they are allowed to mutate config, bypass risk, or call execution tools.

The user needs observability and security from the start, while keeping agent orchestration optional and constrained to coordination, audit, and reporting.

## Solution

Build observability, audit, alerting, and security foundations as core platform capabilities. Structured JSON logs, trace IDs, append-only audit records, metrics, healthchecks, dashboards, alerts, daily and weekly reports, drift detection, and incident workflows will provide operational visibility.

Add agent orchestration only after the deterministic pipeline is stable. Agents may coordinate data checks, news retrieval, forecast calls, ensemble formatting, risk evaluation, audit narration, and reporting, but they must never call order_send, mutate risk config, bypass the risk manager, or store state outside the official audit trail. Tool allowlists, schema validation, refusal tests, and LLM prompt-injection defenses are mandatory.

## User Stories

1. As an operator, I want every tick to have a trace ID, so that forecast, ensemble, risk, execution, and audit events can be followed end to end.
2. As an operator, I want structured JSON logs, so that failures and decisions can be queried reliably.
3. As an operator, I want append-only signal, trade, and audit records, so that no decision history is lost.
4. As an operator, I want metrics for trades, forecasts, errors, kill switches, equity, drawdown, spread, latency, and open positions, so that health is visible in real time.
5. As an operator, I want a dashboard with overview, signals, trades, models, risk, and health views, so that live state can be inspected quickly.
6. As an operator, I want alert severity levels and dedupe, so that important incidents are noticed without alert spam.
7. As an operator, I want critical alerts for order_send failures, MT5 disconnects, kill switch triggers, and drawdown breaches, so that severe issues receive immediate attention.
8. As an operator, I want healthchecks to expose MT5 connection, last tick age, positions, kill switch state, data freshness, and model status, so that service supervisors and dashboards can detect failure.
9. As a quant lead, I want daily and weekly reports, so that performance, rejects, model failures, slippage, and drift are reviewed regularly.
10. As a quant lead, I want drift detection for forecast accuracy, calibration, score distribution, slippage, spread, win rate, Sharpe, and drawdown, so that model degradation is caught early.
11. As a reviewer, I want audit records to include forecasts, ensemble, risk decision, order request, order check, order send, config hash, and code commit, so that every trade can be explained.
12. As a security reviewer, I want secrets stored outside code and config, so that credentials are not committed or logged.
13. As a security reviewer, I want secret masking in logs, so that accidental debug output does not leak credentials.
14. As a security reviewer, I want dependency pinning and supply-chain checks, so that model and package sources are controlled.
15. As a security reviewer, I want hash-chained audit records, so that tampering is detectable.
16. As a security reviewer, I want live risk config governed by review and no hot reload, so that exposure cannot change silently.
17. As a security reviewer, I want bridge authentication for future Option B, so that replay or unauthorized requests cannot submit duplicate signals.
18. As a security reviewer, I want LLM prompt-injection defenses, so that hostile news content cannot instruct an agent to trade or change rules.
19. As an ML engineer, I want agent outputs schema-validated, so that narrative or summary generation cannot corrupt numeric decision fields.
20. As an ML engineer, I want LLM failures to fall back to deterministic behavior, so that the system does not guess under uncertainty.
21. As a backend engineer, I want agents to use tool allowlists, so that each agent can only call permitted capabilities.
22. As a backend engineer, I want no agent allowlist to contain order_send, so that execution remains outside agent control.
23. As a backend engineer, I want the first MVP to support a straight deterministic pipeline, so that agent complexity is optional.
24. As a backend engineer, I want agent orchestration to share the same state schema, so that all steps are inspectable and no global state is hidden.
25. As a QA engineer, I want refusal tests where prompts try to force order_send or risk changes, so that LLM safety rules are enforced.
26. As a QA engineer, I want mocked tool tests for each agent, so that orchestration can be tested without live services.
27. As a QA engineer, I want E2E replay comparing agent orchestration to the straight pipeline, so that agents do not alter deterministic decisions.

## Implementation Decisions

- Build observability and audit before optional agent orchestration.
- Use structured JSONL logging and propagate trace IDs across all decision events.
- Use append-only audit records and make deletion or mutation unavailable to the bot in production.
- Build MVP dashboard with simple local tooling first and production dashboards later.
- Define event taxonomy and metrics names consistently across modules.
- Implement alert dedupe and rate limits, while allowing critical alerts to always send.
- Build healthchecks that expose enough state for service supervision and operator triage.
- Keep daily and weekly reports generated from stored records rather than live memory.
- Add drift detection as monitoring, not as automatic retraining or automatic trading changes.
- Treat the agent layer as optional orchestration and reporting, not as a required trading primitive.
- Prefer a deterministic straight pipeline for MVP.
- If agents are enabled, enforce tool allowlists, state schemas, output schemas, timeouts, token budgets, and audit logging.
- Never include execution order_send or risk config mutation in any agent tool allowlist.
- Store all LLM prompt and response artifacts needed for audit, with secrets and account identifiers redacted.
- Use secret manager or environment-based secrets depending on environment maturity.
- Require supply-chain checks and dependency review for model packages and external repositories.
- Require security incident runbooks and backup procedures before live.

## Testing Decisions

- Good tests verify observable behavior: logs, metrics, alerts, healthcheck output, audit immutability, and agent refusal behavior.
- Unit test log event structure and trace ID propagation.
- Unit test alert dedupe and severity routing.
- Unit test healthcheck responses under healthy, degraded, and failed states.
- Unit test report generation from fixed records.
- Unit test secret masking.
- Unit test audit hash chaining and tamper detection.
- Unit test agent tool allowlists and schema validation.
- Refusal tests must inject prompts and news content that attempt to call order_send, increase lot size, or modify risk config.
- E2E replay should compare agent workflow outputs against the deterministic straight pipeline.
- Security checks should include credential scanning, dependency audit, and permission checks before live.

## Out of Scope

- Letting agents place trades.
- Letting agents modify live risk config.
- Automatic model retraining based on drift detection.
- Full compliance implementation for every jurisdiction.
- Public sharing of copyrighted news datasets.
- Production bridge mTLS unless Option B is implemented.

## Further Notes

Agents should make the system easier to inspect, not more autonomous. The safest interpretation is that agents explain and coordinate deterministic modules, while the deterministic modules remain the source of truth for trading decisions.

