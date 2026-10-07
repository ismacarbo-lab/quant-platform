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


@pytest.mark.parametrize("mode", ["live", "LIVE", "production", "trading", "real"])
def test_live_and_unknown_modes_are_rejected(mode: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_mode=mode)


@pytest.mark.parametrize("mode", ["paper", "PAPER", " paper "])
def test_paper_mode_is_accepted_and_allows_research_tooling(mode: str) -> None:
    settings = Settings(_env_file=None, app_mode=mode)
    assert settings.app_mode is AppMode.PAPER
    assert settings.is_paper_mode is True
    assert settings.is_research_mode is True


def test_research_mode_does_not_allow_paper_writes() -> None:
    settings = Settings(_env_file=None, app_mode="research")
    assert settings.is_paper_mode is False
    assert settings.paper_initial_cash > 0
    assert settings.paper_slippage_bps >= 0


def test_negative_paper_amounts_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, paper_initial_cash="-1")


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
