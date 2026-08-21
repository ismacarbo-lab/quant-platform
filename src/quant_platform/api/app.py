"""Minimal FastAPI application — health only."""

from __future__ import annotations

from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict

from quant_platform import __version__
from quant_platform.core.config import AppMode, Settings, get_settings
from quant_platform.monitoring.logging import configure_logging, get_logger

logger = get_logger("api")


class HealthResponse(BaseModel):
    """Stable, typed health payload. Independent of PostgreSQL and vendors."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"]
    service: str
    version: str
    mode: AppMode


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or get_settings()
    configure_logging(cfg)
    application = FastAPI(
        title="quant_platform",
        version=__version__,
        summary="Quantitative research platform internal API (Phase 0).",
        description="Foundation only. No market data, orders, or broker access.",
    )
    application.state.settings = cfg

    @application.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        logger.debug("health_checked")
        return HealthResponse(
            status="ok",
            service=cfg.service_name,
            version=__version__,
            mode=cfg.app_mode,
        )

    return application


app = create_app()
