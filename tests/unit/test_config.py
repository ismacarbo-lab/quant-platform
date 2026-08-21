"""Configuration loading and safe-by-default behaviour."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from quant_platform.core.config import AppMode, Settings


def test_settings_load_with_explicit_env_file_disabled() -> None:
    settings = Settings(_env_file=None)
    assert settings.app_mode is AppMode.RESEARCH
    assert settings.service_name == "quant_platform"
    assert settings.log_level == "INFO"


def test_default_mode_is_research() -> None:
    settings = Settings(_env_file=None)
    assert settings.is_research_mode is True
    assert settings.app_mode == "research"


@pytest.mark.parametrize("mode", ["live", "LIVE", "paper", "production", "trading"])
def test_non_research_modes_are_rejected(mode: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_mode=mode)


def test_sqlite_database_url_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url="sqlite:///quant.db")


def test_postgresql_url_is_accepted() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://quant:quant_dev_only_not_for_production@127.0.0.1:5434/quant_platform",
    )
    assert settings.database_url.startswith("postgresql")


def test_schema_has_no_broker_or_vendor_secrets() -> None:
    field_names = set(Settings.model_fields)
    forbidden = {
        "api_key",
        "broker_url",
        "broker",
        "live",
        "live_trading",
        "secret",
        "token",
        "polygon_key",
        "alpaca_key",
        "ibkr_host",
    }
    assert field_names.isdisjoint(forbidden)


def test_log_level_is_validated() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, log_level="LOUD")
    settings = Settings(_env_file=None, log_level="debug")
    assert settings.log_level == "DEBUG"
