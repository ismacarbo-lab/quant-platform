"""Market data endpoints: universe coverage, bars, fetch action."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from quant_platform.api.deps import (
    get_db,
    get_jobs,
    get_session_factory,
    get_settings_dep,
)
from quant_platform.api.jobs import JobRegistry
from quant_platform.backtesting.data import PricePanelError, load_price_panel
from quant_platform.core.config import Settings
from quant_platform.data.models import CorporateAction, DailyBar, DataSource, Instrument
from quant_platform.marketdata.universe import (
    DEFAULT_HISTORY_START,
    DEFAULT_UNIVERSE,
    OPTIONAL_UNIVERSE,
    resolve_universe,
)

router = APIRouter(prefix="/api/market", tags=["market"])


class FetchRequest(BaseModel):
    symbols: list[str] | None = None
    include_crypto: bool = False
    start: date = DEFAULT_HISTORY_START
    full_refresh: bool = False
    dry_run: bool = False


class _BarPoint(BaseModel):
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float | None
    adjusted_close: float | None = Field(default=None)


@router.get("/universe")
def universe_coverage(
    settings: Annotated[Settings, Depends(get_settings_dep)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    source = db.scalar(
        select(DataSource).where(DataSource.name == settings.market_data_source_name)
    )
    coverage: dict[str, dict[str, object]] = {}
    if source is not None:
        rows = db.execute(
            select(
                Instrument.symbol,
                func.min(DailyBar.observation_time),
                func.max(DailyBar.observation_time),
                func.count(DailyBar.id),
            )
            .join(Instrument, Instrument.id == DailyBar.instrument_id)
            .where(DailyBar.source_id == source.id)
            .group_by(Instrument.symbol)
        ).all()
        for symbol, first, last, count in rows:
            coverage[str(symbol)] = {
                "first_session": None if first is None else first.date().isoformat(),
                "last_session": None if last is None else last.date().isoformat(),
                "bar_count": int(count),
            }
        dividend_rows = db.execute(
            select(Instrument.symbol, func.count(CorporateAction.id))
            .join(Instrument, Instrument.id == CorporateAction.instrument_id)
            .where(CorporateAction.action_type == "dividend")
            .group_by(Instrument.symbol)
        ).all()
        for symbol, count in dividend_rows:
            coverage.setdefault(str(symbol), {})["dividend_count"] = int(count)
    instruments = []
    for item in DEFAULT_UNIVERSE + OPTIONAL_UNIVERSE:
        payload = item.as_mapping()
        payload["optional"] = item in OPTIONAL_UNIVERSE
        payload["coverage"] = coverage.get(item.symbol)
        instruments.append(payload)
    return {
        "source_name": settings.market_data_source_name,
        "source_present": source is not None,
        "instruments": instruments,
    }


@router.get("/bars/{symbol}")
def bars(
    symbol: str,
    settings: Annotated[Settings, Depends(get_settings_dep)],
    db: Annotated[Session, Depends(get_db)],
    start: Annotated[date | None, Query()] = None,
    end: Annotated[date | None, Query()] = None,
    limit: Annotated[int, Query(ge=10, le=10000)] = 2000,
) -> dict[str, object]:
    token = symbol.strip().upper()
    end_date = end or datetime.now(tz=UTC).date()
    start_date = start or date(end_date.year - 8, 1, 1)
    try:
        panel = load_price_panel(
            db,
            source_name=settings.market_data_source_name,
            symbols=(token,),
            start=start_date,
            end=end_date,
        )
    except PricePanelError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    source = db.scalar(
        select(DataSource).where(DataSource.name == settings.market_data_source_name)
    )
    rows = db.execute(
        select(
            DailyBar.observation_time,
            DailyBar.available_time,
            DailyBar.open,
            DailyBar.high,
            DailyBar.low,
            DailyBar.close,
            DailyBar.volume,
        )
        .join(Instrument, Instrument.id == DailyBar.instrument_id)
        .where(
            Instrument.symbol == token,
            DailyBar.source_id == (source.id if source is not None else None),
            DailyBar.observation_time
            >= datetime.combine(start_date, datetime.min.time(), tzinfo=UTC),
        )
        .order_by(DailyBar.observation_time, DailyBar.available_time)
    ).all()
    latest: dict[str, tuple[Any, ...]] = {}
    for row in rows:
        latest[row[0].date().isoformat()] = tuple(row)
    adjusted = panel.closes[token]
    adjusted_by_day: dict[str, float] = {}
    for position, value in enumerate(adjusted.to_numpy(dtype="float64")):
        if value == value:  # skip NaN
            day = str(adjusted.index[position].date())
            adjusted_by_day[day] = float(value)
    points: list[_BarPoint] = []
    for key in sorted(latest)[-limit:]:
        _obs, _avail, open_, high, low, close, volume = latest[key]
        adj_value = adjusted_by_day.get(key)
        adj_close = None if adj_value is None else round(adj_value, 6)
        points.append(
            _BarPoint(
                date=key,
                open=float(open_),
                high=float(high),
                low=float(low),
                close=float(close),
                volume=None if volume is None else float(volume),
                adjusted_close=adj_close,
            )
        )
    return {
        "symbol": token,
        "source_name": settings.market_data_source_name,
        "count": len(points),
        "bars": [point.model_dump() for point in points],
    }


@router.post("/fetch", status_code=202)
def fetch_market_data(
    body: FetchRequest,
    settings: Annotated[Settings, Depends(get_settings_dep)],
    factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
    jobs: Annotated[JobRegistry, Depends(get_jobs)],
) -> dict[str, object]:
    if jobs.running("market_fetch"):
        raise HTTPException(
            status_code=409, detail="a market data fetch is already running"
        )
    instruments = resolve_universe(body.symbols, include_optional=body.include_crypto)

    def runner() -> dict[str, Any]:
        from quant_platform.marketdata.providers import YFinanceMarketDataProvider
        from quant_platform.marketdata.service import fetch_and_store_market_data

        session = factory()
        try:
            report = fetch_and_store_market_data(
                session,
                YFinanceMarketDataProvider(),
                instruments,
                source_name=settings.market_data_source_name,
                start=body.start,
                write_db=not body.dry_run,
                full_refresh=body.full_refresh,
            )
            return report.as_mapping()
        finally:
            session.close()

    job = jobs.submit("market_fetch", runner, params=body.model_dump(mode="json"))
    return job.as_mapping(include_result=False)
