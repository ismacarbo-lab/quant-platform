"""Credential redaction for logs and operator output."""

from __future__ import annotations

from quant_platform.core.config import Settings
from quant_platform.core.redact import redact_secret_text


def test_redacts_password_in_postgresql_url() -> None:
    raw = "postgresql+psycopg://quant:super-secret@127.0.0.1:5434/quant_platform"
    masked = redact_secret_text(raw)
    assert "super-secret" not in masked
    assert "[redacted]" in masked
    assert "quant" in masked
    assert "127.0.0.1:5434" in masked
    assert "quant_platform" in masked


def test_leaves_non_url_text_unchanged() -> None:
    assert redact_secret_text("ping=ok") == "ping=ok"


def test_settings_display_url_hides_password() -> None:
    settings = Settings(
        _env_file=None,
        database_url=(
            "postgresql+psycopg://quant:hidden-pass@127.0.0.1:5434/quant_platform"
        ),
    )
    assert "hidden-pass" not in settings.database_url_display
    assert settings.database_url.endswith("/quant_platform")
