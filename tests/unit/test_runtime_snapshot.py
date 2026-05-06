"""Issue #11 — runtime_snapshot rollback fingerprint."""

from __future__ import annotations

from pathlib import Path

from ai_mt5.config.models import AppConfig
from ai_mt5.runtime.snapshot import RuntimeSnapshot, runtime_snapshot


def test_snapshot_is_deterministic_for_same_config(app_config: AppConfig) -> None:
    a = runtime_snapshot(config=app_config)
    b = runtime_snapshot(config=app_config)
    assert a.config_hash == b.config_hash
    assert a.commit == b.commit


def test_snapshot_changes_when_config_changes(app_config: AppConfig) -> None:
    a = runtime_snapshot(config=app_config)
    mutated = app_config.model_copy(
        update={
            "environment": app_config.environment.model_copy(
                update={
                    "log_level": "DEBUG" if app_config.environment.log_level != "DEBUG" else "INFO"
                }
            )
        }
    )
    b = runtime_snapshot(config=mutated)
    assert a.config_hash != b.config_hash


def test_snapshot_handles_missing_git(tmp_path: Path, app_config: AppConfig) -> None:
    snap = runtime_snapshot(config=app_config, repo_root=tmp_path)
    assert isinstance(snap, RuntimeSnapshot)
    assert snap.commit == "unknown"
    # config_hash still computed even without git.
    assert len(snap.config_hash) == 64


def test_snapshot_to_dict_is_json_safe(app_config: AppConfig) -> None:
    import json

    snap = runtime_snapshot(config=app_config)
    payload = snap.to_dict()
    assert json.dumps(payload, sort_keys=True) is not None
    assert set(payload.keys()) == {"commit", "config_hash"}
