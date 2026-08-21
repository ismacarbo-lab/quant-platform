"""Redact credentials that must never appear in logs or operator output."""

from __future__ import annotations

import re

# postgresql://user:password@host and postgresql+psycopg://user:password@host
_URL_PASSWORD = re.compile(
    r"(?i)((?:postgresql(?:\+\w+)?|postgres)://[^:/\s]+:)([^@\s]+)(@)"
)


def redact_secret_text(value: str) -> str:
    """Mask passwords embedded in PostgreSQL URLs. Other text is unchanged."""
    return _URL_PASSWORD.sub(r"\1[redacted]\3", value)
