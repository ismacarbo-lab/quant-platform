"""Manual calendars and optional session validation on ingest."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from quant_platform.data.csv_loader import ErrorMode
from quant_platform.data.ingest import ingest_daily_bars_csv
from quant_platform.data.repository import (
    create_ingestion_run,
    get_daily_bars,
    list_ingestion_errors,
    upsert_data_source,
    upsert_instrument,
    upsert_market_calendar,
    upsert_market_session,
)

pytestmark = pytest.mark.postgres

CAL_CSV = Path(__file__).resolve().parents[1] / "fixtures" / "daily_bars_calendar.csv"


def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:8]}"


def test_calendar_open_and_closed_sessions(db_session: Session) -> None:
    calendar = upsert_market_calendar(
        db_session, code=_unique("cal"), name="Test", timezone="UTC"
    )
    open_row = upsert_market_session(
        db_session,
        calendar_id=calendar.id,
        session_date=date(2024, 1, 2),
        is_open=True,
        note="regular",
    )
    closed = upsert_market_session(
        db_session,
        calendar_id=calendar.id,
        session_date=date(2024, 1, 1),
        is_open=False,
        note="holiday",
    )
    assert open_row.is_open is True
    assert closed.is_open is False
    again = upsert_market_session(
        db_session,
        calendar_id=calendar.id,
        session_date=date(2024, 1, 2),
        is_open=True,
        note="updated",
    )
    assert again.id == open_row.id
    assert again.note == "updated"


def test_ingest_without_calendar_validation_accepts_closed_day(
    db_session: Session,
) -> None:
    source = upsert_data_source(db_session, name=_unique("src"), vendor="local_csv")
    run = create_ingestion_run(db_session, source_id=source.id)
    calendar = upsert_market_calendar(
        db_session, code=_unique("cal"), name="Test", timezone="UTC"
    )
    upsert_market_session(
        db_session,
        calendar_id=calendar.id,
        session_date=date(2024, 1, 2),
        is_open=True,
    )
    upsert_market_session(
        db_session,
        calendar_id=calendar.id,
        session_date=date(2024, 1, 3),
        is_open=False,
    )
    result = ingest_daily_bars_csv(
        db_session,
        CAL_CSV,
        source=source,
        run=run,
        asset_class="equity",
        error_mode=ErrorMode.COLLECT_ERRORS,
        validate_calendar=False,
        calendar_id=calendar.id,
    )
    assert result.accepted_count == 2
    assert result.rejected_count == 0
    instrument = upsert_instrument(
        db_session, symbol="CAL", asset_class="equity", calendar_id=calendar.id
    )
    bars = get_daily_bars(db_session, instrument_id=instrument.id, source_id=source.id)
    assert len(bars) == 2


def test_ingest_with_calendar_validation_rejects_closed_session(
    db_session: Session,
) -> None:
    source = upsert_data_source(db_session, name=_unique("src"), vendor="local_csv")
    run = create_ingestion_run(db_session, source_id=source.id)
    calendar = upsert_market_calendar(
        db_session, code=_unique("cal"), name="Test", timezone="UTC"
    )
    upsert_market_session(
        db_session,
        calendar_id=calendar.id,
        session_date=date(2024, 1, 2),
        is_open=True,
    )
    upsert_market_session(
        db_session,
        calendar_id=calendar.id,
        session_date=date(2024, 1, 3),
        is_open=False,
        note="holiday",
    )
    result = ingest_daily_bars_csv(
        db_session,
        CAL_CSV,
        source=source,
        run=run,
        asset_class="equity",
        error_mode=ErrorMode.COLLECT_ERRORS,
        validate_calendar=True,
        calendar_id=calendar.id,
    )
    assert result.accepted_count == 1
    assert result.rejected_count == 1
    errors = list_ingestion_errors(db_session, ingestion_run_id=run.id)
    assert len(errors) == 1
    assert errors[0].error_code == "closed_session"
    instrument = upsert_instrument(
        db_session, symbol="CAL", asset_class="equity", calendar_id=calendar.id
    )
    bars = get_daily_bars(db_session, instrument_id=instrument.id, source_id=source.id)
    assert len(bars) == 1
    assert bars[0].observation_time.day == 2
