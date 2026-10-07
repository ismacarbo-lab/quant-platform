"""Typed application settings with safe defaults.

Sensitive values are read from the environment. There is no live-trading
mode, broker URL, or market-data API key in this schema. Paper trading is
simulated locally with fictional cash (see ADR 0005).
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from quant_platform.core.redact import redact_secret_text


class AppMode(StrEnum):
    """Operational mode.

    ``research`` runs the data and research tooling only. ``paper`` adds the
    simulated paper-trading engine with fictional money. Live execution is
    not implemented and is rejected if configured.
    """

    RESEARCH = "research"
    PAPER = "paper"


SUPPORTED_APP_MODES: frozenset[str] = frozenset(mode.value for mode in AppMode)


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
            "@127.0.0.1:5434/quant_platform"
        )
    )
    # Market data source used by ``fetch-market-data`` and the paper engine.
    market_data_source_name: str = "yfinance"
    # Paper trading (fictional cash, simulated fills). Never real money.
    paper_initial_cash: Decimal = Decimal("100000")
    # One paper account per strategy is bootstrapped on the first run so the
    # dashboard can compare them side by side ("paper horse race").
    paper_default_strategies: str = (
        "inverse_volatility,trend_following,relative_momentum_top_n,"
        "dual_momentum,sixty_forty,buy_and_hold"
    )
    paper_rebalance: str = "monthly"
    paper_commission_bps: Decimal = Decimal("1")
    paper_slippage_bps: Decimal = Decimal("5")
    # Optional built dashboard directory served by the API (static files).
    dashboard_dist_dir: str = "dashboard/dist"

    @field_validator("app_mode", mode="before")
    @classmethod
    def reject_unsupported_modes(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized not in SUPPORTED_APP_MODES:
                msg = (
                    f"Unsupported app mode {value!r}. Allowed modes are "
                    f"{sorted(SUPPORTED_APP_MODES)}; live trading is not implemented."
                )
                raise ValueError(msg)
            return normalized
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

    @field_validator("paper_initial_cash", "paper_commission_bps", "paper_slippage_bps")
    @classmethod
    def require_non_negative(cls, value: Decimal) -> Decimal:
        if value < 0:
            msg = "paper trading amounts must not be negative"
            raise ValueError(msg)
        return value

    @property
    def is_research_mode(self) -> bool:
        """True when research tooling may run (research or paper; never live)."""
        return self.app_mode in (AppMode.RESEARCH, AppMode.PAPER)

    @property
    def is_paper_mode(self) -> bool:
        """True only when the simulated paper-trading engine may write state."""
        return self.app_mode is AppMode.PAPER

    @property
    def database_url_display(self) -> str:
        """DATABASE_URL with the password masked. Safe for logs and errors."""
        return redact_secret_text(self.database_url)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load settings once per process. Clear the cache in tests."""
    return Settings()


def clear_settings_cache() -> None:
    get_settings.cache_clear()
