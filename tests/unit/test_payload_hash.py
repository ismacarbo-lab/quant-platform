"""Stable bronze payload hashing."""

from __future__ import annotations

from quant_platform.data.payload import (
    canonical_json,
    payload_sha256,
    redact_payload_secrets,
)


def test_payload_hash_independent_of_key_order() -> None:
    first = payload_sha256({"b": "1", "a": "2"})
    second = payload_sha256({"a": "2", "b": "1"})
    assert first == second
    assert len(first) == 64
    assert first == payload_sha256({"a": "2", "b": "1"})


def test_payload_hash_changes_when_value_changes() -> None:
    assert payload_sha256({"symbol": "A"}) != payload_sha256({"symbol": "B"})


def test_canonical_json_sorts_keys() -> None:
    assert canonical_json({"b": 1, "a": 2}) == '{"a":2,"b":1}'


def test_secret_keys_are_redacted_before_hash() -> None:
    hashed = payload_sha256({"symbol": "A", "password": "hunter2"})
    assert hashed == payload_sha256({"symbol": "A", "password": "[redacted]"})
    assert "hunter2" not in str(redact_payload_secrets({"password": "hunter2"}))
