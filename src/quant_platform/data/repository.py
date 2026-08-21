"""Persistence helpers for research ingestion. No strategy or broker logic."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from quant_platform.core.time import utc_now
from quant_platform.data.models import (
    DailyBar,
    DataSource,
    IngestionError,
    IngestionRun,
    IngestionStatus,
    Instrument,
    RawIngestionRecord,
)
from quant_platform.data.validation import DailyBarDraft, validate_daily_bar_draft


def upsert_data_source(
    session: Session,
    *,
    name: str,
    vendor: str,
    description: str | None = None,
) -> DataSource:
    existing = session.scalar(select(DataSource).where(DataSource.name == name))
    if existing is not None:
        existing.vendor = vendor
        existing.description = description
        session.flush()
        return existing
    source = DataSource(name=name, vendor=vendor, description=description)
    session.add(source)
    session.flush()
    return source


def upsert_instrument(
    session: Session,
    *,
    symbol: str,
    asset_class: str,
    name: str | None = None,
    currency: str | None = None,
    exchange: str | None = None,
) -> Instrument:
    key = symbol.strip()
    existing = session.scalar(select(Instrument).where(Instrument.symbol == key))
    if existing is not None:
        existing.asset_class = asset_class
        existing.name = name
        existing.currency = currency
        existing.exchange = exchange
        session.flush()
        return existing
    instrument = Instrument(
        symbol=key,
        asset_class=asset_class,
        name=name,
        currency=currency,
        exchange=exchange,
    )
    session.add(instrument)
    session.flush()
    return instrument


def create_ingestion_run(
    session: Session,
    *,
    source_id: UUID,
    run_metadata: dict[str, Any] | None = None,
) -> IngestionRun:
    run = IngestionRun(
        source_id=source_id,
        started_at=utc_now(),
        status=IngestionStatus.STARTED.value,
        row_count=0,
        accepted_count=0,
        rejected_count=0,
        run_metadata=run_metadata,
    )
    session.add(run)
    session.flush()
    return run


def finish_ingestion_run(
    session: Session,
    run: IngestionRun,
    *,
    status: IngestionStatus,
    row_count: int,
    accepted_count: int | None = None,
    rejected_count: int | None = None,
    error_message: str | None = None,
) -> IngestionRun:
    run.status = status.value
    run.row_count = row_count
    if accepted_count is not None:
        run.accepted_count = accepted_count
    if rejected_count is not None:
        run.rejected_count = rejected_count
    run.finished_at = utc_now()
    run.error_message = error_message
    session.flush()
    return run


def insert_daily_bars(
    session: Session,
    *,
    drafts: list[DailyBarDraft],
    instruments_by_symbol: dict[str, Instrument],
    source_id: UUID,
    ingestion_run_id: UUID,
) -> int:
    """Insert bars. Duplicate PIT keys are ignored (idempotent)."""
    validated = [validate_daily_bar_draft(draft) for draft in drafts]
    payload: list[dict[str, object]] = []
    for draft in validated:
        instrument = instruments_by_symbol.get(draft.symbol)
        if instrument is None:
            msg = f"no instrument registered for symbol {draft.symbol!r}"
            raise KeyError(msg)
        payload.append(
            {
                "id": uuid4(),
                "instrument_id": instrument.id,
                "source_id": source_id,
                "observation_time": draft.observation_time,
                "available_time": draft.available_time,
                "open": draft.open,
                "high": draft.high,
                "low": draft.low,
                "close": draft.close,
                "volume": draft.volume,
                "ingestion_run_id": ingestion_run_id,
                "created_at": utc_now(),
            }
        )
    if not payload:
        return 0
    stmt = (
        insert(DailyBar)
        .values(payload)
        .on_conflict_do_nothing(constraint="uq_daily_bars_pit")
        .returning(DailyBar.id)
    )
    inserted_ids = list(session.scalars(stmt))
    session.flush()
    return len(inserted_ids)


def insert_raw_record(
    session: Session,
    *,
    ingestion_run_id: UUID,
    source_id: UUID,
    record_index: int,
    raw_payload: dict[str, object],
    payload_hash: str,
    received_at: datetime | None = None,
) -> RawIngestionRecord:
    record = RawIngestionRecord(
        ingestion_run_id=ingestion_run_id,
        source_id=source_id,
        record_index=record_index,
        raw_payload=raw_payload,
        payload_hash=payload_hash,
        received_at=received_at or utc_now(),
    )
    session.add(record)
    session.flush()
    return record


def insert_ingestion_error(
    session: Session,
    *,
    ingestion_run_id: UUID,
    source_id: UUID,
    error_code: str,
    error_message: str,
    record_index: int | None = None,
    raw_payload: dict[str, object] | None = None,
) -> IngestionError:
    error = IngestionError(
        ingestion_run_id=ingestion_run_id,
        source_id=source_id,
        record_index=record_index,
        error_code=error_code,
        error_message=error_message,
        raw_payload=raw_payload,
    )
    session.add(error)
    session.flush()
    return error


def get_raw_records_for_run(
    session: Session, *, ingestion_run_id: UUID
) -> list[RawIngestionRecord]:
    stmt = (
        select(RawIngestionRecord)
        .where(RawIngestionRecord.ingestion_run_id == ingestion_run_id)
        .order_by(RawIngestionRecord.record_index)
    )
    return list(session.scalars(stmt))


def list_ingestion_errors(
    session: Session, *, ingestion_run_id: UUID
) -> list[IngestionError]:
    stmt = (
        select(IngestionError)
        .where(IngestionError.ingestion_run_id == ingestion_run_id)
        .order_by(IngestionError.record_index.nulls_last(), IngestionError.created_at)
    )
    return list(session.scalars(stmt))


def get_daily_bars(
    session: Session,
    *,
    instrument_id: UUID,
    source_id: UUID | None = None,
    as_of: datetime | None = None,
) -> list[DailyBar]:
    """Return stored bars.

    When ``as_of`` is set, only rows with ``available_time <= as_of`` are
    considered, and the latest correction per ``(source_id, observation_time)``
    is returned. Future versions are excluded. Without ``as_of``, every PIT
    version is returned (audit).
    """
    stmt: Select[tuple[DailyBar]] = select(DailyBar).where(
        DailyBar.instrument_id == instrument_id
    )
    if source_id is not None:
        stmt = stmt.where(DailyBar.source_id == source_id)
    if as_of is not None:
        stmt = (
            stmt.where(DailyBar.available_time <= as_of)
            .distinct(DailyBar.source_id, DailyBar.observation_time)
            .order_by(
                DailyBar.source_id,
                DailyBar.observation_time,
                DailyBar.available_time.desc(),
            )
        )
    else:
        stmt = stmt.order_by(DailyBar.observation_time, DailyBar.available_time)
    return list(session.scalars(stmt))
