"""Load YAML config files and validate them via pydantic.

The loader supports:
  - ``${VAR}`` and ``${VAR:default}`` substitution from environment variables.
  - Layered loading: ``config.yaml`` < ``envs/<ENV>.yaml`` < explicit overrides.

Validation errors are surfaced as :class:`ConfigError` so that ``main`` can
fail fast with a clean message instead of a pydantic stack trace.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from .models import AppConfig

_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::([^}]*))?\}")


class ConfigError(ValueError):
    """Raised when the config is missing required keys or fails validation."""


def _substitute_env(value: Any, env: Mapping[str, str]) -> Any:
    if isinstance(value, str):

        def replace(match: re.Match[str]) -> str:
            var, default = match.group(1), match.group(2)
            if var in env:
                return env[var]
            if default is not None:
                return default
            raise ConfigError(f"environment variable {var!r} is not set and has no default")

        return _VAR_PATTERN.sub(replace, value)
    if isinstance(value, dict):
        return {k: _substitute_env(v, env) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute_env(v, env) for v in value]
    return value


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``override`` into ``base``. Lists are replaced wholesale."""
    out = dict(base)
    for key, val in override.items():
        if key in out and isinstance(out[key], dict) and isinstance(val, dict):
            out[key] = _deep_merge(out[key], val)
        else:
            out[key] = val
    return out


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(f"config file {path} must be a mapping, got {type(raw).__name__}")
    return raw


def load_config(
    path: str | os.PathLike[str],
    *,
    overrides: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
) -> AppConfig:
    """Load and validate the application config.

    Args:
        path: Path to the main YAML config (e.g. ``config/config.yaml``).
        overrides: Optional dict deep-merged on top of the YAML (used by tests
            and CLI flags).
        env: Mapping for ``${VAR}`` substitution. Defaults to ``os.environ``.

    Returns:
        A fully validated :class:`AppConfig`.

    Raises:
        ConfigError: If the file is missing required keys, contains an unknown
            key, or fails pydantic validation.
    """
    env = dict(env) if env is not None else dict(os.environ)
    main_path = Path(path)
    raw = _read_yaml(main_path)

    if overrides:
        raw = _deep_merge(raw, dict(overrides))

    raw = _substitute_env(raw, env)

    required_keys = {"environment", "symbols", "storage", "risk", "execution"}
    missing = required_keys - set(raw)
    if missing:
        raise ConfigError(f"config is missing required top-level keys: {sorted(missing)}")

    # Allow `symbols:` to be either a list or a {"symbols": [...]} subdoc.
    symbols = raw["symbols"]
    if isinstance(symbols, dict) and "symbols" in symbols:
        raw["symbols"] = symbols["symbols"]

    try:
        return AppConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"invalid config: {exc}") from exc
