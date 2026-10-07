"""FastAPI application: health, dashboard JSON API and static dashboard."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.types import Scope

from quant_platform import __version__
from quant_platform.api.jobs import JobRegistry
from quant_platform.api.routes import (
    backtests_router,
    jobs_router,
    market_router,
    paper_router,
    status_router,
    strategies_router,
)
from quant_platform.core.config import AppMode, Settings, get_settings
from quant_platform.monitoring.logging import configure_logging, get_logger
from quant_platform.release.status import repository_root

logger = get_logger("api")


class SPAStaticFiles(StaticFiles):
    """Serve the built dashboard; unknown paths fall back to index.html."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            is_api = path.startswith(("api/", "api", "health"))
            if (
                exc.status_code == 404
                and not is_api
                and "." not in path.rsplit("/", 1)[-1]
            ):
                return await super().get_response("index.html", scope)
            raise


class HealthResponse(BaseModel):
    """Stable, typed health payload. Independent of PostgreSQL and vendors."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"]
    service: str
    version: str
    mode: AppMode


@asynccontextmanager
async def _lifespan(application: FastAPI) -> AsyncIterator[None]:
    yield
    engine = getattr(application.state, "engine", None)
    if engine is not None:
        engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or get_settings()
    configure_logging(cfg)
    application = FastAPI(
        title="quant_platform",
        version=__version__,
        summary="Local dashboard API: market data, strategy backtests, paper trading.",
        description=(
            "Simulated paper trading with fictional money. No live trading, no "
            "real broker, no credentials."
        ),
        lifespan=_lifespan,
    )
    application.state.settings = cfg
    application.state.jobs = JobRegistry()

    @application.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        logger.debug("health_checked")
        return HealthResponse(
            status="ok",
            service=cfg.service_name,
            version=__version__,
            mode=cfg.app_mode,
        )

    application.include_router(status_router)
    application.include_router(market_router)
    application.include_router(strategies_router)
    application.include_router(backtests_router)
    application.include_router(paper_router)
    application.include_router(jobs_router)

    dist = _dashboard_dist(cfg)
    if dist is not None:
        application.mount(
            "/", SPAStaticFiles(directory=str(dist), html=True), name="dashboard"
        )
    return application


def _dashboard_dist(settings: Settings) -> Path | None:
    raw = settings.dashboard_dist_dir.strip()
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        try:
            path = repository_root() / path
        except FileNotFoundError:
            return None
    if (path / "index.html").is_file():
        return path
    return None


app = create_app()
