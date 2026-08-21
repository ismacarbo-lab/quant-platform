"""Explicit point-in-time daily bar corrections."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from quant_platform.data.repository import (
    create_exchange,
    create_ingestion_run,
    get_daily_bars,
    insert_daily_bar_correction,
    insert_daily_bars,
    upsert_data_source,
    upsert_instrument,
)
from quant_platform.data.validation import DailyBarDraft, DataValidationError

pytestmark = pytest.mark.postgres


def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:8]}"


def test_explicit_correction_and_as_of(db_session: Session) -> None:
    source = upsert_data_source(db_session, name=_unique("src"), vendor="local_csv")
    venue = create_exchange(db_session, code=_unique("XNYS"), timezone="UTC")
    instrument = upsert_instrument(
        db_session,
        symbol=_unique("COR"),
        asset_class="equity",
        exchange_id=venue.id,
    )
    run = create_ingestion_run(db_session, source_id=source.id)
    original_draft = DailyBarDraft(
        symbol=instrument.symbol,
        observation_time=datetime(2024, 1, 1, tzinfo=UTC),
        available_time=datetime(2024, 1, 2, tzinfo=UTC),
        open=Decimal("10"),
        high=Decimal("11"),
        low=Decimal("9"),
        close=Decimal("10"),
        volume=None,
    )
    assert (
        insert_daily_bars(
            db_session,
            drafts=[original_draft],
            instruments_by_symbol={instrument.symbol: instrument},
            source_id=source.id,
            ingestion_run_id=run.id,
        )
        == 1
    )
    original = get_daily_bars(db_session, instrument_id=instrument.id)[0]
    assert original.is_correction is False
    correction = insert_daily_bar_correction(
        db_session,
        superseded=original,
        available_time=datetime(2024, 1, 5, tzinfo=UTC),
        open=Decimal("10"),
        high=Decimal("12"),
        low=Decimal("9"),
        close=Decimal("11"),
        volume=None,
        ingestion_run_id=run.id,
        reason="restated close",
    )
    assert correction.is_correction is True
    assert correction.supersedes_daily_bar_id == original.id
    assert original.superseded_by_daily_bar_id == correction.id
    assert correction.correction_reason == "restated close"
    as_of_early = get_daily_bars(
        db_session,
        instrument_id=instrument.id,
        as_of=datetime(2024, 1, 3, tzinfo=UTC),
    )
    assert len(as_of_early) == 1
    assert as_of_early[0].id == original.id
    as_of_late = get_daily_bars(
        db_session,
        instrument_id=instrument.id,
        as_of=datetime(2024, 1, 6, tzinfo=UTC),
    )
    assert len(as_of_late) == 1
    assert as_of_late[0].id == correction.id
    history = get_daily_bars(db_session, instrument_id=instrument.id)
    assert len(history) == 2
    assert original.id in {row.id for row in history}


def test_stale_correction_is_rejected(db_session: Session) -> None:
    source = upsert_data_source(db_session, name=_unique("src"), vendor="local_csv")
    instrument = upsert_instrument(
        db_session, symbol=_unique("STALE"), asset_class="equity"
    )
    run = create_ingestion_run(db_session, source_id=source.id)
    draft = DailyBarDraft(
        symbol=instrument.symbol,
        observation_time=datetime(2024, 1, 1, tzinfo=UTC),
        available_time=datetime(2024, 1, 5, tzinfo=UTC),
        open=Decimal("10"),
        high=Decimal("11"),
        low=Decimal("9"),
        close=Decimal("10"),
        volume=None,
    )
    insert_daily_bars(
        db_session,
        drafts=[draft],
        instruments_by_symbol={instrument.symbol: instrument},
        source_id=source.id,
        ingestion_run_id=run.id,
    )
    original = get_daily_bars(db_session, instrument_id=instrument.id)[0]
    with pytest.raises(DataValidationError, match="after the superseded"):
        insert_daily_bar_correction(
            db_session,
            superseded=original,
            available_time=datetime(2024, 1, 3, tzinfo=UTC),
            open=Decimal("10"),
            high=Decimal("11"),
            low=Decimal("9"),
            close=Decimal("10.5"),
            volume=None,
            ingestion_run_id=run.id,
            reason="too early",
        )
