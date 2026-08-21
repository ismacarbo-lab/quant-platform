"""Stable SHA-256 hashing of bronze payloads. No network."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

_SECRET_KEYS = frozenset(
    {
        "password",
        "secret",
        "token",
        "api_key",
        "apikey",
        "database_url",
        "access_token",
        "refresh_token",
    }
)


def redact_payload_secrets(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Copy a mapping, replacing secret-like keys. Used before hash and store."""
    redacted: dict[str, Any] = {}
    for key, value in payload.items():
        lowered = key.strip().lower()
        if lowered in _SECRET_KEYS or lowered.endswith("_password"):
            redacted[key] = "[redacted]"
        elif isinstance(value, dict):
            redacted[key] = redact_payload_secrets(value)
        else:
            redacted[key] = value
    return redacted


def _jsonable(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, UUID):
        return str(value)
    return value


def canonical_json(payload: Mapping[str, Any]) -> str:
    """UTF-8 JSON with sorted keys and compact separators."""
    return json.dumps(
        _jsonable(dict(payload)),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def payload_sha256(payload: Mapping[str, Any]) -> str:
    """SHA-256 hex digest of the redacted canonical JSON payload."""
    canonical = canonical_json(redact_payload_secrets(payload))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
