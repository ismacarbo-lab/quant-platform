"""PostgreSQL contract-payload intake. Research-only, no trading tables."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from quant_platform.core.config import Settings
from quant_platform.data.contracts import (
    VendorPayloadBatch,
    build_contract_payload_intake_request,
    execute_contract_payload_intake,
    load_offline_vendor_payload_batch,
    relabel_contract_payload_batch,
)
from quant_platform.data.models import (
    CorporateAction,
    DailyBar,
    DataSource,
    Instrument,
    MarketSession,
    RawIngestionRecord,
)
from quant_platform.data.repository import get_market_calendar_by_code
from quant_platform.simulation.constructs import FORBIDDEN_TABLE_NAMES
from quant_platform.storage.database import list_public_tables

pytestmark = pytest.mark.postgres

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "contract_payload_intake"


def _isolated_batch(name: str) -> VendorPayloadBatch:
    batch = load_offline_vendor_payload_batch(_FIXTURES / name / "batch.json")
    token = uuid4().hex[:8]
    source = f"offline_intake_{token}"
    symbol = f"ITK{token[:5].upper()}"
    calendar = f"cal_{token}"
    labeled = relabel_contract_payload_batch(batch, source)
    bars = tuple(replace(item, symbol=symbol) for item in labeled.daily_bars)
    actions = tuple(replace(item, symbol=symbol) for item in labeled.corporate_actions)
    sessions = tuple(
        replace(item, calendar_code=calendar, symbol=symbol)
        for item in labeled.market_sessions
    )
    return VendorPayloadBatch(
        source_name=source,
        contract=replace(labeled.contract, source_name=source),
        daily_bars=bars,
        corporate_actions=actions,
        market_sessions=sessions,
    )


def _source(session: Session, name: str) -> DataSource | None:
    return session.scalar(select(DataSource).where(DataSource.name == name))


def _bar_count(session: Session, source_id: object) -> int:
    counted = session.scalar(
        select(func.count())
        .select_from(DailyBar)
        .where(DailyBar.source_id == source_id)
    )
    return int(counted or 0)


def test_write_db_inserts_valid_batch(
    db_session: Session, research_settings: Settings
) -> None:
    assert research_settings.is_research_mode is True
    batch = _isolated_batch("valid_dry_run")
    request = build_contract_payload_intake_request(
        source_name=batch.source_name,
        write_db=True,
    )
    report = execute_contract_payload_intake(db_session, batch, request)
    assert report.ok is True
    assert report.db_executed is True
    assert report.inserted_counts.daily_bars == 1
    assert report.inserted_counts.corporate_actions == 1
    assert report.inserted_counts.market_sessions == 1
    source = _source(db_session, batch.source_name)
    assert source is not None
    assert source.vendor == "offline_contract"
    assert _bar_count(db_session, source.id) == 1
    raw = list(
        db_session.scalars(
            select(RawIngestionRecord).where(RawIngestionRecord.source_id == source.id)
        )
    )
    assert len(raw) == 3
    assert all(len(item.payload_hash) == 64 for item in raw)
    instrument = db_session.scalar(
        select(Instrument).where(Instrument.symbol == batch.daily_bars[0].symbol)
    )
    assert instrument is not None
    actions = list(
        db_session.scalars(
            select(CorporateAction).where(
                CorporateAction.instrument_id == instrument.id
            )
        )
    )
    assert len(actions) == 1
    assert actions[0].action_type == "split"
    calendar = get_market_calendar_by_code(
        db_session, code=batch.market_sessions[0].calendar_code
    )
    assert calendar is not None
    sessions = list(
        db_session.scalars(
            select(MarketSession).where(MarketSession.calendar_id == calendar.id)
        )
    )
    assert len(sessions) == 1


def test_second_execution_is_idempotent_and_does_not_mutate_bars(
    db_session: Session,
) -> None:
    batch = _isolated_batch("valid_dry_run")
    request = build_contract_payload_intake_request(
        source_name=batch.source_name,
        write_db=True,
    )
    first = execute_contract_payload_intake(db_session, batch, request)
    source = _source(db_session, batch.source_name)
    assert source is not None
    bars = list(
        db_session.scalars(select(DailyBar).where(DailyBar.source_id == source.id))
    )
    assert len(bars) == 1
    original = (
        bars[0].id,
        bars[0].open,
        bars[0].high,
        bars[0].low,
        bars[0].close,
        bars[0].volume,
        bars[0].available_time,
        bars[0].observation_time,
        bars[0].is_correction,
    )
    second = execute_contract_payload_intake(db_session, batch, request)
    assert first.inserted_counts.daily_bars == 1
    assert second.db_executed is True
    assert second.inserted_counts.daily_bars == 0
    assert second.skipped_counts.daily_bars == 1
    assert second.inserted_counts.corporate_actions == 0
    assert second.skipped_counts.corporate_actions == 1
    assert second.inserted_counts.market_sessions == 0
    assert second.skipped_counts.market_sessions == 1
    bars_after = list(
        db_session.scalars(select(DailyBar).where(DailyBar.source_id == source.id))
    )
    assert len(bars_after) == 1
    row = bars_after[0]
    assert (
        row.id,
        row.open,
        row.high,
        row.low,
        row.close,
        row.volume,
        row.available_time,
        row.observation_time,
        row.is_correction,
    ) == original


def test_invalid_batch_does_not_write(db_session: Session) -> None:
    batch = _isolated_batch("invalid_batch_rejected")
    request = build_contract_payload_intake_request(
        source_name=batch.source_name,
        write_db=True,
    )
    report = execute_contract_payload_intake(db_session, batch, request)
    assert report.ok is False
    assert report.db_executed is False
    assert _source(db_session, batch.source_name) is None
    raw = list(db_session.scalars(select(RawIngestionRecord)))
    assert all(item.source_id != batch.source_name for item in raw)


def test_app_mode_research_and_no_trading_tables(
    db_session: Session,
    research_settings: Settings,
    postgres_engine,
) -> None:
    assert research_settings.is_research_mode is True
    tables = set(list_public_tables(postgres_engine))
    assert tables.isdisjoint(FORBIDDEN_TABLE_NAMES)
    for name in ("orders", "fills", "trades", "positions", "portfolios", "pnl"):
        assert name not in tables
