"""PostgreSQL ingestion repository tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from quant_platform.data.csv_loader import load_daily_bars_csv
from quant_platform.data.models import IngestionStatus
from quant_platform.data.repository import (
    create_ingestion_run,
    finish_ingestion_run,
    get_daily_bars,
    insert_daily_bars,
    upsert_data_source,
    upsert_instrument,
)
from quant_platform.data.validation import DailyBarDraft

pytestmark = pytest.mark.postgres

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "daily_bars_sample.csv"


def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:8]}"


def test_upsert_source_and_instrument(db_session: Session) -> None:
    name = _unique("src")
    symbol = _unique("SYM")
    first = upsert_data_source(db_session, name=name, vendor="local_csv")
    second = upsert_data_source(
        db_session, name=name, vendor="manual_fixture", description="updated"
    )
    assert first.id == second.id
    assert second.vendor == "manual_fixture"
    inst_a = upsert_instrument(db_session, symbol=symbol, asset_class="equity")
    inst_b = upsert_instrument(
        db_session, symbol=symbol, asset_class="equity", currency="USD"
    )
    assert inst_a.id == inst_b.id
    assert inst_b.currency == "USD"


def test_insert_daily_bars_and_pit_query(db_session: Session) -> None:
    source = upsert_data_source(db_session, name=_unique("src"), vendor="local_csv")
    instrument = upsert_instrument(
        db_session, symbol=_unique("AAA"), asset_class="equity"
    )
    run = create_ingestion_run(db_session, source_id=source.id)
    draft = DailyBarDraft(
        symbol=instrument.symbol,
        observation_time=datetime(2024, 1, 2, tzinfo=UTC),
        available_time=datetime(2024, 1, 3, tzinfo=UTC),
        open=Decimal("10"),
        high=Decimal("11"),
        low=Decimal("9"),
        close=Decimal("10.5"),
        volume=Decimal("1000"),
    )
    inserted = insert_daily_bars(
        db_session,
        drafts=[draft],
        instruments_by_symbol={instrument.symbol: instrument},
        source_id=source.id,
        ingestion_run_id=run.id,
    )
    assert inserted == 1
    again = insert_daily_bars(
        db_session,
        drafts=[draft],
        instruments_by_symbol={instrument.symbol: instrument},
        source_id=source.id,
        ingestion_run_id=run.id,
    )
    assert again == 0
    as_of_before = get_daily_bars(
        db_session,
        instrument_id=instrument.id,
        as_of=datetime(2024, 1, 2, 12, 0, tzinfo=UTC),
    )
    assert as_of_before == []
    as_of_after = get_daily_bars(
        db_session,
        instrument_id=instrument.id,
        as_of=datetime(2024, 1, 3, tzinfo=UTC),
    )
    assert len(as_of_after) == 1
    assert as_of_after[0].close == Decimal("10.5")
    finish_ingestion_run(
        db_session, run, status=IngestionStatus.SUCCEEDED, row_count=inserted
    )
    assert run.status == IngestionStatus.SUCCEEDED.value
    assert run.finished_at is not None


def test_load_fixture_csv_into_postgres(db_session: Session) -> None:
    drafts = load_daily_bars_csv(FIXTURE)
    source = upsert_data_source(db_session, name=_unique("csv"), vendor="local_csv")
    run = create_ingestion_run(db_session, source_id=source.id)
    instruments = {
        symbol: upsert_instrument(db_session, symbol=symbol, asset_class="equity")
        for symbol in {row.symbol for row in drafts}
    }
    inserted = insert_daily_bars(
        db_session,
        drafts=drafts,
        instruments_by_symbol=instruments,
        source_id=source.id,
        ingestion_run_id=run.id,
    )
    assert inserted == 3
    fixt = instruments["FIXT"]
    bars = get_daily_bars(db_session, instrument_id=fixt.id, source_id=source.id)
    assert len(bars) == 2
    assert bars[0].available_time > bars[0].observation_time
