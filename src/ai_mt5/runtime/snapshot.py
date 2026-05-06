"""Capture the commit SHA + config hash for rollback bookkeeping.

Issue #11 acceptance criterion: "Rollback uses commit and config
snapshot references." The :func:`runtime_snapshot` function returns a
small, auditable structure embeddable in audit records and promotion
reports.

The implementation is deliberately tolerant: a missing ``.git`` (e.g.
running from an installed wheel) or unavailable ``git`` binary yields
``commit='unknown'`` instead of raising. Operators can still rely on
``config_hash`` to detect config drift even without git history.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RuntimeSnapshot:
    """Commit + config fingerprint for rollback / forensics."""

    commit: str
    config_hash: str

    def to_dict(self) -> dict[str, str]:
        return {"commit": self.commit, "config_hash": self.config_hash}


def _resolve_commit(repo_root: Path) -> str:
    if not (repo_root / ".git").exists():
        return "unknown"
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return "unknown"
    return out.stdout.strip() or "unknown"


def _hash_config(config: Any) -> str:
    """Stable SHA-256 of a JSON-serialisable config object.

    Pydantic models are converted via ``model_dump`` first; anything
    else must already be JSON-serialisable.
    """
    if hasattr(config, "model_dump"):
        payload = config.model_dump(mode="json")
    elif isinstance(config, dict):
        payload = config
    else:
        payload = json.loads(json.dumps(config, default=str))
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def runtime_snapshot(*, config: Any, repo_root: Path | None = None) -> RuntimeSnapshot:
    """Build a :class:`RuntimeSnapshot` for the running process.

    Parameters
    ----------
    config:
        The validated :class:`~ai_mt5.config.models.AppConfig` (or any
        JSON-serialisable mapping). Hashed deterministically.
    repo_root:
        Override for the git repo root. Defaults to walking up from
        this file until a ``.git`` directory is found, falling back to
        the current working directory.
    """
    root = repo_root or _find_repo_root(Path(__file__).resolve())
    return RuntimeSnapshot(
        commit=_resolve_commit(root),
        config_hash=_hash_config(config),
    )


def _find_repo_root(start: Path) -> Path:
    cur = start
    for _ in range(10):
        if (cur / ".git").exists():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return Path.cwd()


__all__ = ["RuntimeSnapshot", "runtime_snapshot"]
