"""Optional Agent Layer (issue #12).

The straight pipeline (``TickRunner``) is the **source of truth**. The
Agent Layer is a thin orchestrator that:

* may call a fixed allow-listed set of read-only tools on the
  deterministic modules (forecast, ensemble, risk evaluation);
* never invokes ``order_send``, ``risk config mutation``, or any tool
  outside the allowlist;
* produces an Audit Narration whose schema is validated against
  :class:`AgentNarration`; on schema failure the agent falls back to the
  deterministic decision verbatim and logs a ``narration_invalid`` audit
  event.

A replay test asserts that for any ``(bars, config, seed)`` the
agent-orchestrated path produces the same trade ledger and audit
hash chain as the straight pipeline.
"""

from __future__ import annotations

from .layer import AgentLayer, AgentResult, NarrationFallback
from .narration import AgentNarration, NarrationValidationError, validate_narration
from .tools import (
    AGENT_TOOL_ALLOWLIST,
    AgentToolset,
    DenyMutationError,
)

__all__ = [
    "AGENT_TOOL_ALLOWLIST",
    "AgentLayer",
    "AgentNarration",
    "AgentResult",
    "AgentToolset",
    "DenyMutationError",
    "NarrationFallback",
    "NarrationValidationError",
    "validate_narration",
]
