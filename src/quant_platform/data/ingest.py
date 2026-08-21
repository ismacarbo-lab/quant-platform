"""Persist local CSV into bronze records and silver daily bars."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session

from quant_platform.data.csv_loader import ErrorMode, iter_csv_rows, parse_daily_bar_row
from quant_platform.data.models import DataSource, IngestionRun, Instrument
from quant_platform.data.payload import payload_sha256, redact_payload_secrets
from quant_platform.data.repository import (
    insert_daily_bars,
    insert_ingestion_error,
    insert_raw_record,
    require_open_session,
    upsert_instrument,
)
from quant_platform.data.validation import DataValidationError, IngestionErrorCode


@dataclass(frozen=True, slots=True)
class IngestResult:
    accepted_count: int
    rejected_count: int
    inserted_bars: int
    aborted: bool


def ingest_daily_bars_csv(
    session: Session,
    path: Path,
    *,
    source: DataSource,
    run: IngestionRun,
    asset_class: str,
    currency: str | None = None,
    exchange: str | None = None,
    error_mode: ErrorMode = ErrorMode.COLLECT_ERRORS,
    validate_calendar: bool = False,
    calendar_id: UUID | None = None,
) -> IngestResult:
    """Store raw rows, then silver bars or ingestion errors.

    Bronze records are written before validation. ``collect_errors`` continues
    after a bad row. ``fail_fast`` records the first error and returns with
    ``aborted=True`` (does not raise, so the session can be committed).

    ``validate_calendar`` (default False) rejects bars whose instrument has a
    calendar without an open session on the observation date.
    """
    accepted = 0
    rejected = 0
    inserted_bars = 0
    instruments: dict[str, Instrument] = {}
    saw_row = False

    for record_index, row in iter_csv_rows(path):
        saw_row = True
        payload = redact_payload_secrets(dict(row))
        digest = payload_sha256(payload)
        insert_raw_record(
            session,
            ingestion_run_id=run.id,
            source_id=source.id,
            record_index=record_index,
            raw_payload=payload,
            payload_hash=digest,
        )
        try:
            draft = parse_daily_bar_row(row)
        except DataValidationError as exc:
            insert_ingestion_error(
                session,
                ingestion_run_id=run.id,
                source_id=source.id,
                record_index=record_index,
                error_code=exc.code,
                error_message=str(exc),
                raw_payload=payload,
            )
            rejected += 1
            if error_mode is ErrorMode.FAIL_FAST:
                return IngestResult(
                    accepted_count=accepted,
                    rejected_count=rejected,
                    inserted_bars=inserted_bars,
                    aborted=True,
                )
            continue
        instrument = instruments.get(draft.symbol)
        if instrument is None:
            instrument = upsert_instrument(
                session,
                symbol=draft.symbol,
                asset_class=asset_class,
                currency=currency,
                exchange=exchange,
                calendar_id=calendar_id,
            )
            instruments[draft.symbol] = instrument
        if validate_calendar:
            try:
                require_open_session(
                    session,
                    instrument=instrument,
                    observation_time=draft.observation_time,
                )
            except DataValidationError as exc:
                insert_ingestion_error(
                    session,
                    ingestion_run_id=run.id,
                    source_id=source.id,
                    record_index=record_index,
                    error_code=exc.code,
                    error_message=str(exc),
                    raw_payload=payload,
                )
                rejected += 1
                if error_mode is ErrorMode.FAIL_FAST:
                    return IngestResult(
                        accepted_count=accepted,
                        rejected_count=rejected,
                        inserted_bars=inserted_bars,
                        aborted=True,
                    )
                continue
        inserted_bars += insert_daily_bars(
            session,
            drafts=[draft],
            instruments_by_symbol=instruments,
            source_id=source.id,
            ingestion_run_id=run.id,
        )
        accepted += 1

    if not saw_row:
        insert_ingestion_error(
            session,
            ingestion_run_id=run.id,
            source_id=source.id,
            error_code=IngestionErrorCode.EMPTY_FILE,
            error_message="CSV contains no data rows",
        )
        return IngestResult(
            accepted_count=0,
            rejected_count=1,
            inserted_bars=0,
            aborted=True,
        )

    return IngestResult(
        accepted_count=accepted,
        rejected_count=rejected,
        inserted_bars=inserted_bars,
        aborted=False,
    )
