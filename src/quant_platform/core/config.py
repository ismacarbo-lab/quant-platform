"""Typed application settings with a safe research-only default.

Sensitive values are read from the environment. There is no live-trading
mode, broker URL, or market-data API key in this schema.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppMode(StrEnum):
    """Operational mode.

    Phase 0 supports research only. Paper trading and live execution are
    future modes and are rejected if configured.
    """

    RESEARCH = "research"


class Settings(BaseSettings):
    """Central configuration. Defaults are safe for local research use."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    service_name: str = "quant_platform"
    app_mode: AppMode = AppMode.RESEARCH
    log_level: str = "INFO"
    # Fictional local-dev default (same placeholder as docker-compose / .env.example).
    # Override via DATABASE_URL. Not a production secret.
    database_url: str = Field(
        default=(
            "postgresql+psycopg://quant:quant_dev_only_not_for_production"
            "@127.0.0.1:5432/quant_platform"
        )
    )

    @field_validator("app_mode", mode="before")
    @classmethod
    def reject_non_research_modes(cls, value: object) -> object:
        if isinstance(value, str) and value.strip().lower() != AppMode.RESEARCH:
            msg = (
                f"Unsupported app mode {value!r}. Phase 0 only allows "
                f"{AppMode.RESEARCH!r}; live and paper trading are not implemented."
            )
            raise ValueError(msg)
        return value

    @field_validator("database_url")
    @classmethod
    def require_postgresql(cls, value: str) -> str:
        if not value.startswith("postgresql"):
            msg = (
                "DATABASE_URL must use PostgreSQL "
                "(postgresql:// or postgresql+psycopg://). "
                "SQLite is not an allowed substitute."
            )
            raise ValueError(msg)
        return value

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        level = value.strip().upper()
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if level not in allowed:
            msg = f"LOG_LEVEL must be one of {sorted(allowed)}, got {value!r}"
            raise ValueError(msg)
        return level

    @property
    def is_research_mode(self) -> bool:
        return self.app_mode is AppMode.RESEARCH


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load settings once per process. Clear the cache in tests."""
    return Settings()


def clear_settings_cache() -> None:
    get_settings.cache_clear()
