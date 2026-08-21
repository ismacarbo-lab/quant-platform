"""PostgreSQL bronze ingest and point-in-time correction queries."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from quant_platform.data.csv_loader import ErrorMode
from quant_platform.data.ingest import ingest_daily_bars_csv
from quant_platform.data.models import IngestionStatus
from quant_platform.data.repository import (
    create_ingestion_run,
    finish_ingestion_run,
    get_daily_bars,
    get_raw_records_for_run,
    insert_daily_bars,
    list_ingestion_errors,
    upsert_data_source,
    upsert_instrument,
)
from quant_platform.data.validation import DailyBarDraft

pytestmark = pytest.mark.postgres

MIXED = Path(__file__).resolve().parents[1] / "fixtures" / "daily_bars_mixed.csv"
SAMPLE = Path(__file__).resolve().parents[1] / "fixtures" / "daily_bars_sample.csv"


def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:8]}"


def test_ingest_collect_errors_stores_raw_and_errors(db_session: Session) -> None:
    source = upsert_data_source(db_session, name=_unique("src"), vendor="local_csv")
    run = create_ingestion_run(db_session, source_id=source.id)
    result = ingest_daily_bars_csv(
        db_session,
        MIXED,
        source=source,
        run=run,
        asset_class="equity",
        error_mode=ErrorMode.COLLECT_ERRORS,
    )
    assert result.accepted_count == 2
    assert result.rejected_count == 1
    assert result.inserted_bars == 2
    assert result.aborted is False
    raw = get_raw_records_for_run(db_session, ingestion_run_id=run.id)
    assert len(raw) == 3
    assert all(len(record.payload_hash) == 64 for record in raw)
    errors = list_ingestion_errors(db_session, ingestion_run_id=run.id)
    assert len(errors) == 1
    assert errors[0].error_code == "invalid_ohlc"
    assert errors[0].record_index == 1
    finish_ingestion_run(
        db_session,
        run,
        status=IngestionStatus.SUCCEEDED,
        row_count=result.accepted_count + result.rejected_count,
        accepted_count=result.accepted_count,
        rejected_count=result.rejected_count,
    )
    assert run.accepted_count == 2
    assert run.rejected_count == 1


def test_ingest_fail_fast_stops_after_first_error(db_session: Session) -> None:
    source = upsert_data_source(db_session, name=_unique("src"), vendor="local_csv")
    run = create_ingestion_run(db_session, source_id=source.id)
    result = ingest_daily_bars_csv(
        db_session,
        MIXED,
        source=source,
        run=run,
        asset_class="equity",
        error_mode=ErrorMode.FAIL_FAST,
    )
    assert result.accepted_count == 1
    assert result.rejected_count == 1
    assert result.aborted is True
    raw = get_raw_records_for_run(db_session, ingestion_run_id=run.id)
    assert len(raw) == 2
    errors = list_ingestion_errors(db_session, ingestion_run_id=run.id)
    assert len(errors) == 1


def test_as_of_returns_latest_visible_correction(db_session: Session) -> None:
    source = upsert_data_source(db_session, name=_unique("src"), vendor="local_csv")
    instrument = upsert_instrument(
        db_session, symbol=_unique("COR"), asset_class="equity"
    )
    run = create_ingestion_run(db_session, source_id=source.id)
    observation = datetime(2024, 1, 1, tzinfo=UTC)
    first = DailyBarDraft(
        symbol=instrument.symbol,
        observation_time=observation,
        available_time=datetime(2024, 1, 2, tzinfo=UTC),
        open=Decimal("10"),
        high=Decimal("11"),
        low=Decimal("9"),
        close=Decimal("10"),
        volume=None,
    )
    correction = DailyBarDraft(
        symbol=instrument.symbol,
        observation_time=observation,
        available_time=datetime(2024, 1, 5, tzinfo=UTC),
        open=Decimal("10"),
        high=Decimal("12"),
        low=Decimal("9"),
        close=Decimal("11"),
        volume=None,
    )
    assert (
        insert_daily_bars(
            db_session,
            drafts=[first, correction],
            instruments_by_symbol={instrument.symbol: instrument},
            source_id=source.id,
            ingestion_run_id=run.id,
        )
        == 2
    )
    as_of_early = get_daily_bars(
        db_session,
        instrument_id=instrument.id,
        source_id=source.id,
        as_of=datetime(2024, 1, 3, tzinfo=UTC),
    )
    assert len(as_of_early) == 1
    assert as_of_early[0].close == Decimal("10")
    assert as_of_early[0].available_time == datetime(2024, 1, 2, tzinfo=UTC)
    as_of_late = get_daily_bars(
        db_session,
        instrument_id=instrument.id,
        source_id=source.id,
        as_of=datetime(2024, 1, 6, tzinfo=UTC),
    )
    assert len(as_of_late) == 1
    assert as_of_late[0].close == Decimal("11")
    assert as_of_late[0].available_time == datetime(2024, 1, 5, tzinfo=UTC)
    future = get_daily_bars(
        db_session,
        instrument_id=instrument.id,
        as_of=datetime(2024, 1, 1, 12, 0, tzinfo=UTC),
    )
    assert future == []
    history = get_daily_bars(db_session, instrument_id=instrument.id)
    assert len(history) == 2


def test_sample_csv_ingest_writes_bronze(db_session: Session) -> None:
    source = upsert_data_source(db_session, name=_unique("csv"), vendor="local_csv")
    run = create_ingestion_run(db_session, source_id=source.id)
    result = ingest_daily_bars_csv(
        db_session,
        SAMPLE,
        source=source,
        run=run,
        asset_class="equity",
        error_mode=ErrorMode.COLLECT_ERRORS,
    )
    assert result.accepted_count == 3
    assert result.rejected_count == 0
    assert len(get_raw_records_for_run(db_session, ingestion_run_id=run.id)) == 3
    assert list_ingestion_errors(db_session, ingestion_run_id=run.id) == []
