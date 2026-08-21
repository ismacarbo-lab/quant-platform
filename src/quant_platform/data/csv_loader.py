"""Parse local research CSV files. No network, no market-data vendors."""

from __future__ import annotations

import csv
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path

from quant_platform.data.validation import (
    DailyBarDraft,
    DataValidationError,
    IngestionErrorCode,
    parse_decimal,
    validate_daily_bar_draft,
)

REQUIRED_COLUMNS = (
    "symbol",
    "date",
    "open",
    "high",
    "low",
    "close",
    "available_time",
)


class ErrorMode(StrEnum):
    FAIL_FAST = "fail_fast"
    COLLECT_ERRORS = "collect_errors"


class CsvLoadError(DataValidationError):
    """CSV syntax or row-level ingestion error."""

    def __init__(
        self, message: str, *, code: str = IngestionErrorCode.CSV_ERROR
    ) -> None:
        super().__init__(message, code=code)


@dataclass(frozen=True, slots=True)
class CsvRowError:
    record_index: int
    line_number: int
    error_code: str
    error_message: str
    raw_payload: dict[str, str | None]


def parse_utc_datetime(value: str, *, field: str) -> datetime:
    text = value.strip()
    if not text:
        raise CsvLoadError(f"{field} is required")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise CsvLoadError(
            f"{field} is not a valid timestamp: {value!r}",
            code=IngestionErrorCode.NAIVE_TIMESTAMP,
        ) from exc
    if parsed.tzinfo is None:
        raise CsvLoadError(
            f"{field} must include a timezone (got naive {value!r})",
            code=IngestionErrorCode.NAIVE_TIMESTAMP,
        )
    return parsed.astimezone(UTC)


def parse_observation_time(value: str) -> datetime:
    """Interpret ``date`` as observation_time.

    A calendar date ``YYYY-MM-DD`` is midnight UTC on that date. Datetimes
    must already be timezone-aware.
    """
    text = value.strip()
    if not text:
        raise CsvLoadError("date is required")
    if "T" in text or " " in text or text.endswith("Z") or "+" in text[1:]:
        return parse_utc_datetime(text, field="date")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise CsvLoadError(
            f"date is not a valid date or timestamp: {value!r}",
            code=IngestionErrorCode.NAIVE_TIMESTAMP,
        ) from exc
    if parsed.tzinfo is not None:
        return parsed.astimezone(UTC)
    return datetime(parsed.year, parsed.month, parsed.day, tzinfo=UTC)


def _optional_volume(raw: str | None) -> Decimal | None:
    if raw is None:
        return None
    text = raw.strip()
    if text == "":
        return None
    return parse_decimal(text, field="volume")


def _require_columns(fieldnames: Sequence[str] | None) -> list[str]:
    if fieldnames is None:
        raise CsvLoadError(
            "CSV has no header row", code=IngestionErrorCode.MISSING_COLUMNS
        )
    columns = [name.strip() for name in fieldnames]
    missing = [name for name in REQUIRED_COLUMNS if name not in columns]
    if missing:
        raise CsvLoadError(
            f"CSV missing required columns: {missing}",
            code=IngestionErrorCode.MISSING_COLUMNS,
        )
    return columns


def ensure_csv_readable(path: Path) -> None:
    """Fail fast on missing file or header. Does not read data rows."""
    if not path.is_file():
        raise CsvLoadError(
            f"CSV file not found: {path}", code=IngestionErrorCode.FILE_NOT_FOUND
        )
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        _require_columns(reader.fieldnames)


def iter_csv_rows(path: Path) -> Iterator[tuple[int, dict[str, str | None]]]:
    """Yield ``(record_index, raw_row)`` for data rows. Index is 0-based."""
    ensure_csv_readable(path)
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        _require_columns(reader.fieldnames)
        for record_index, row in enumerate(reader):
            yield record_index, dict(row)


def parse_daily_bar_row(row: dict[str, str | None]) -> DailyBarDraft:
    """Validate one CSV row into a silver draft."""
    volume_raw = row.get("volume")
    draft = DailyBarDraft(
        symbol=str(row.get("symbol") or ""),
        observation_time=parse_observation_time(str(row.get("date") or "")),
        available_time=parse_utc_datetime(
            str(row.get("available_time") or ""), field="available_time"
        ),
        open=parse_decimal(row.get("open"), field="open"),
        high=parse_decimal(row.get("high"), field="high"),
        low=parse_decimal(row.get("low"), field="low"),
        close=parse_decimal(row.get("close"), field="close"),
        volume=_optional_volume(volume_raw),
    )
    return validate_daily_bar_draft(draft)


def parse_csv_file(
    path: Path, *, error_mode: ErrorMode = ErrorMode.FAIL_FAST
) -> tuple[list[DailyBarDraft], list[CsvRowError]]:
    """Parse a CSV. ``fail_fast`` raises; ``collect_errors`` returns rejects."""
    accepted: list[DailyBarDraft] = []
    rejected: list[CsvRowError] = []
    saw_row = False
    for record_index, row in iter_csv_rows(path):
        saw_row = True
        try:
            accepted.append(parse_daily_bar_row(row))
        except DataValidationError as exc:
            error = CsvRowError(
                record_index=record_index,
                line_number=record_index + 2,
                error_code=exc.code,
                error_message=str(exc),
                raw_payload=row,
            )
            if error_mode is ErrorMode.FAIL_FAST:
                raise CsvLoadError(
                    f"row {error.line_number}: {exc}", code=exc.code
                ) from exc
            rejected.append(error)
    if not saw_row:
        raise CsvLoadError(
            "CSV contains no data rows", code=IngestionErrorCode.EMPTY_FILE
        )
    return accepted, rejected


def load_daily_bars_csv(path: Path) -> list[DailyBarDraft]:
    """Load and validate daily bars (fail-fast)."""
    accepted, _rejected = parse_csv_file(path, error_mode=ErrorMode.FAIL_FAST)
    return accepted
