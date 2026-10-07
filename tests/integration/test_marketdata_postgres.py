"""Market data fetch writes through intake idempotently. Requires PostgreSQL."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

import pandas as pd
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from quant_platform.data.models import (
    CorporateAction,
    DailyBar,
    DataSource,
    Instrument,
    RawIngestionRecord,
)
from quant_platform.marketdata.providers import RecordedMarketDataProvider
from quant_platform.marketdata.service import (
    fetch_and_store_market_data,
    last_stored_session,
)
from quant_platform.marketdata.universe import UniverseInstrument

pytestmark = pytest.mark.postgres

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "marketdata"
_NOW = datetime(2024, 4, 1, 12, 0, tzinfo=UTC)


def _count_bars(session: Session, symbol: str, source_name: str) -> int:
    stmt = (
        select(func.count(DailyBar.id))
        .join(Instrument, Instrument.id == DailyBar.instrument_id)
        .join(DataSource, DataSource.id == DailyBar.source_id)
        .where(Instrument.symbol == symbol, DataSource.name == source_name)
    )
    return int(session.scalar(stmt) or 0)


def _count_dividends(session: Session, symbol: str) -> int:
    stmt = (
        select(func.count(CorporateAction.id))
        .join(Instrument, Instrument.id == CorporateAction.instrument_id)
        .where(Instrument.symbol == symbol, CorporateAction.action_type == "dividend")
    )
    return int(session.scalar(stmt) or 0)


def test_fetch_writes_then_is_idempotent_and_records_restatements(
    db_session: Session,
) -> None:
    token = uuid4().hex[:8]
    source_name = f"yf_test_{token}"
    symbol = f"T{token[:6].upper()}"
    frame = RecordedMarketDataProvider(_FIXTURES).fetch_history(
        "SPY", start=date(2024, 1, 1), end=date(2024, 3, 31)
    )
    provider = RecordedMarketDataProvider(_FIXTURES, frames={symbol: frame})
    instrument = UniverseInstrument(symbol, "test", "etf", "risk", "test")

    first = fetch_and_store_market_data(
        db_session,
        provider,
        (instrument,),
        source_name=source_name,
        start=date(2024, 1, 1),
        end=date(2024, 3, 31),
        now=_NOW,
        commit=False,
    )
    assert first.ok is True
    assert first.symbols[0].status == "written"
    assert first.inserted_daily_bars == 60
    assert first.inserted_corporate_actions == 1
    assert _count_bars(db_session, symbol, source_name) == 60
    assert _count_dividends(db_session, symbol) == 1
    assert last_stored_session(db_session, symbol=symbol, source_name=source_name) == (
        date(2024, 3, 25)
    )
    raw_count = db_session.scalar(select(func.count(RawIngestionRecord.id))) or 0
    assert raw_count >= 61

    second = fetch_and_store_market_data(
        db_session,
        provider,
        (instrument,),
        source_name=source_name,
        start=date(2024, 1, 1),
        end=date(2024, 3, 31),
        now=_NOW,
        commit=False,
    )
    assert second.ok is True
    assert second.symbols[0].status == "up_to_date"
    assert second.inserted_daily_bars == 0
    assert _count_bars(db_session, symbol, source_name) == 60
    assert _count_dividends(db_session, symbol) == 1
    # Incremental fetch only looked back a few days, not the full history.
    assert provider.calls[-1][1] >= date(2024, 3, 1)

    restated = frame.copy()
    last_day = restated.index[-1]
    restated.loc[last_day, "Close"] = float(restated.loc[last_day, "Close"]) * 1.02
    restated.loc[last_day, "High"] = max(
        float(restated.loc[last_day, "High"]), float(restated.loc[last_day, "Close"])
    )
    later = datetime(2024, 4, 2, 12, 0, tzinfo=UTC)
    third = fetch_and_store_market_data(
        db_session,
        RecordedMarketDataProvider(_FIXTURES, frames={symbol: restated}),
        (instrument,),
        source_name=source_name,
        start=date(2024, 1, 1),
        end=date(2024, 3, 31),
        now=later,
        commit=False,
    )
    assert third.ok is True
    assert third.symbols[0].payload is not None
    assert third.symbols[0].payload.corrections_emitted == 1
    assert third.inserted_daily_bars == 1
    assert _count_bars(db_session, symbol, source_name) == 61
    rows = list(
        db_session.scalars(
            select(DailyBar)
            .join(Instrument, Instrument.id == DailyBar.instrument_id)
            .where(Instrument.symbol == symbol)
            .order_by(DailyBar.observation_time, DailyBar.available_time)
        )
    )
    original_last = [r for r in rows if r.observation_time.date() == date(2024, 3, 25)]
    assert len(original_last) == 2
    assert original_last[0].available_time < original_last[1].available_time
    assert original_last[1].available_time == later
    assert original_last[0].close != original_last[1].close
    assert isinstance(frame, pd.DataFrame)


def test_dry_run_plans_without_writing(db_session: Session) -> None:
    token = uuid4().hex[:8]
    source_name = f"yf_dry_{token}"
    symbol = f"D{token[:6].upper()}"
    frame = RecordedMarketDataProvider(_FIXTURES).fetch_history(
        "BIL", start=date(2024, 1, 1), end=date(2024, 3, 31)
    )
    provider = RecordedMarketDataProvider(_FIXTURES, frames={symbol: frame})
    report = fetch_and_store_market_data(
        db_session,
        provider,
        (UniverseInstrument(symbol, "test", "etf", "cash", "test"),),
        source_name=source_name,
        start=date(2024, 1, 1),
        end=date(2024, 3, 31),
        now=_NOW,
        write_db=False,
        commit=False,
    )
    assert report.ok is True
    assert report.symbols[0].status == "planned"
    assert report.symbols[0].intake_hash
    assert _count_bars(db_session, symbol, source_name) == 0
    assert (
        db_session.scalar(select(DataSource).where(DataSource.name == source_name))
        is None
    )
