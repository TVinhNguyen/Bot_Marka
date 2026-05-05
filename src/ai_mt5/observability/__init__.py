"""Observability + governance: health, metrics, alerts, reports, audit chain.

Per issue #12, this slice is offline-only. The MT5-dependent pieces
(``connection_state``, broker-side last tick age) are exposed through a
``MT5StatusProvider`` Protocol so #11 can swap in the real implementation
later without touching call sites.
"""

from __future__ import annotations

from .alerts import Alert, AlertManager, AlertRule, Severity, dedupe_key
from .chain import HashChainedAuditTrail, chain_records, verify_chain
from .health import HealthSnapshot, HealthStatus, MT5StatusProvider, build_health
from .masking import SECRET_FIELD_NAMES, mask_secrets
from .metrics import MetricSnapshot, MetricsRegistry
from .report import OperationsReport, build_period_report

__all__ = [
    "SECRET_FIELD_NAMES",
    "Alert",
    "AlertManager",
    "AlertRule",
    "HashChainedAuditTrail",
    "HealthSnapshot",
    "HealthStatus",
    "MT5StatusProvider",
    "MetricSnapshot",
    "MetricsRegistry",
    "OperationsReport",
    "Severity",
    "build_health",
    "build_period_report",
    "chain_records",
    "dedupe_key",
    "mask_secrets",
    "verify_chain",
]
