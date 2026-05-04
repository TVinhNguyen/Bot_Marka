"""Secret masking for audit / log payloads."""

from __future__ import annotations

from ai_mt5.observability.masking import MASK, SECRET_FIELD_NAMES, mask_secrets


def test_mask_replaces_known_keys_at_any_depth() -> None:
    payload = {
        "user": "alice",
        "password": "p@ss",
        "nested": {
            "api_key": "sk-very-secret",
            "ok": "fine",
            "deeper": {"refresh_token": "rt"},
        },
        "tokens": [{"token": "abc"}, {"token": "def"}],
    }
    out = mask_secrets(payload)
    assert out["user"] == "alice"
    assert out["password"] == MASK
    assert out["nested"]["api_key"] == MASK
    assert out["nested"]["ok"] == "fine"
    assert out["nested"]["deeper"]["refresh_token"] == MASK
    assert out["tokens"][0]["token"] == MASK
    assert out["tokens"][1]["token"] == MASK


def test_mask_is_case_insensitive() -> None:
    payload = {"PASSWORD": "x", "Api_Key": "y"}
    out = mask_secrets(payload)
    assert out["PASSWORD"] == MASK
    assert out["Api_Key"] == MASK


def test_mask_does_not_mutate_input() -> None:
    payload = {"password": "before"}
    mask_secrets(payload)
    assert payload["password"] == "before"


def test_known_secret_keys_present() -> None:
    # Smoke list -- the runtime must mask these by default.
    for name in {
        "password",
        "api_key",
        "openai_api_key",
        "fingpt_api_key",
        "private_key",
        "broker_password",
        "webhook_secret",
    }:
        assert name in SECRET_FIELD_NAMES


def test_mask_preserves_lists_and_tuples() -> None:
    payload = {"chain": [1, 2, {"token": "secret"}], "tup": ({"password": "p"}, 42)}
    out = mask_secrets(payload)
    assert out["chain"][2]["token"] == MASK
    assert isinstance(out["tup"], tuple)
    assert out["tup"][0]["password"] == MASK
    assert out["tup"][1] == 42
