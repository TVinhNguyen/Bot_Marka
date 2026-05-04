"""Secret masking helpers for audit / log payloads.

Anything written to disk or shipped to a third-party log aggregator
should pass through :func:`mask_secrets` first. The default field list
covers MT5 login, broker password, OpenAI / FinGPT API keys, and webhook
tokens; callers may extend it.
"""

from __future__ import annotations

from typing import Any

#: Field names whose *values* are treated as secret regardless of where they
#: appear in a payload tree.
SECRET_FIELD_NAMES: frozenset[str] = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "api_key",
        "api_token",
        "token",
        "access_token",
        "refresh_token",
        "mt5_password",
        "broker_password",
        "openai_api_key",
        "fingpt_api_key",
        "webhook_token",
        "webhook_secret",
        "private_key",
    }
)

MASK = "***"


def mask_secrets(
    payload: Any,
    *,
    secret_keys: frozenset[str] = SECRET_FIELD_NAMES,
) -> Any:
    """Return a deep copy of ``payload`` with secret values replaced by ``"***"``.

    Mutating in place is deliberately not supported: audit records are
    frozen dataclasses, and operating on a copy keeps this function safe
    to call from logging hooks.
    """
    if isinstance(payload, dict):
        out: dict[str, Any] = {}
        for k, v in payload.items():
            if isinstance(k, str) and k.lower() in secret_keys:
                out[k] = MASK
            else:
                out[k] = mask_secrets(v, secret_keys=secret_keys)
        return out
    if isinstance(payload, list):
        return [mask_secrets(v, secret_keys=secret_keys) for v in payload]
    if isinstance(payload, tuple):
        return tuple(mask_secrets(v, secret_keys=secret_keys) for v in payload)
    return payload
