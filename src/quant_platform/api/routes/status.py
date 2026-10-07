"""Platform status for the dashboard header."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from quant_platform import __version__
from quant_platform.api.deps import get_db, get_settings_dep
from quant_platform.backtesting.models import StrategyBacktestRecord
from quant_platform.core.config import Settings
from quant_platform.data.models import DailyBar, DataSource, Instrument
from quant_platform.marketdata.universe import DEFAULT_UNIVERSE, OPTIONAL_UNIVERSE
from quant_platform.paper.models import PaperAccount
from quant_platform.release.constants import (
    DISABLED_CAPABILITIES,
    ENABLED_CAPABILITIES,
    EXPECTED_ALEMBIC_HEAD,
)

router = APIRouter(prefix="/api", tags=["status"])


@router.get("/status")
def platform_status(
    settings: Annotated[Settings, Depends(get_settings_dep)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    database: dict[str, object] = {"reachable": False}
    try:
        source = db.scalar(
            select(DataSource).where(
                DataSource.name == settings.market_data_source_name
            )
        )
        last_session = None
        bar_count = 0
        symbol_count = 0
        if source is not None:
            last_session = db.scalar(
                select(func.max(DailyBar.observation_time)).where(
                    DailyBar.source_id == source.id
                )
            )
            bar_count = int(
                db.scalar(
                    select(func.count(DailyBar.id)).where(
                        DailyBar.source_id == source.id
                    )
                )
                or 0
            )
            symbol_count = int(
                db.scalar(
                    select(func.count(func.distinct(DailyBar.instrument_id))).where(
                        DailyBar.source_id == source.id
                    )
                )
                or 0
            )
        backtests = int(db.scalar(select(func.count(StrategyBacktestRecord.id))) or 0)
        accounts = int(db.scalar(select(func.count(PaperAccount.id))) or 0)
        instruments = int(db.scalar(select(func.count(Instrument.id))) or 0)
        database = {
            "reachable": True,
            "market_data_source": settings.market_data_source_name,
            "market_data_present": source is not None,
            "last_session": None
            if last_session is None
            else last_session.date().isoformat(),
            "bar_count": bar_count,
            "symbol_count": symbol_count,
            "instrument_count": instruments,
            "backtest_count": backtests,
            "paper_account_count": accounts,
        }
    except SQLAlchemyError as exc:
        database = {"reachable": False, "error": type(exc).__name__}
    return {
        "service": settings.service_name,
        "version": __version__,
        "mode": settings.app_mode.value,
        "paper_enabled": settings.is_paper_mode,
        "live_trading": "disabled",
        "real_money": False,
        "alembic_head_expected": EXPECTED_ALEMBIC_HEAD,
        "universe": [item.as_mapping() for item in DEFAULT_UNIVERSE],
        "optional_universe": [item.as_mapping() for item in OPTIONAL_UNIVERSE],
        "capabilities": {
            "enabled": list(ENABLED_CAPABILITIES),
            "disabled": list(DISABLED_CAPABILITIES),
        },
        "database": database,
        "disclaimer": (
            "Simulated paper trading with fictional money. Backtests and paper "
            "results do not guarantee future returns."
        ),
    }
