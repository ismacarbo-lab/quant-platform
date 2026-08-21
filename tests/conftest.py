"""Shared pytest fixtures. Unit tests do not open network connections."""

from __future__ import annotations

import pytest

from quant_platform.core.config import Settings, clear_settings_cache


@pytest.fixture
def research_settings() -> Settings:
    clear_settings_cache()
    return Settings(_env_file=None, app_mode="research")


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> None:
    clear_settings_cache()
    yield
    clear_settings_cache()
