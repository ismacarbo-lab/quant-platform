"""Dashboard JSON API routers (local use)."""

from quant_platform.api.routes.backtests import router as backtests_router
from quant_platform.api.routes.jobs import router as jobs_router
from quant_platform.api.routes.market import router as market_router
from quant_platform.api.routes.paper import router as paper_router
from quant_platform.api.routes.status import router as status_router
from quant_platform.api.routes.strategies import router as strategies_router

__all__ = [
    "backtests_router",
    "jobs_router",
    "market_router",
    "paper_router",
    "status_router",
    "strategies_router",
]
