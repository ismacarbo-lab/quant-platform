"""Parse local research CSV files. No network, no market-data vendors."""

from __future__ import annotations

import csv
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from quant_platform.data.validation import (
    DailyBarDraft,
    DataValidationError,
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


class CsvLoadError(DataValidationError):
    """CSV syntax or row-level ingestion error."""


def parse_utc_datetime(value: str, *, field: str) -> datetime:
    text = value.strip()
    if not text:
        raise CsvLoadError(f"{field} is required")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise CsvLoadError(f"{field} is not a valid timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise CsvLoadError(f"{field} must include a timezone (got naive {value!r})")
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
        raise CsvLoadError(f"date is not a valid date or timestamp: {value!r}") from exc
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


def load_daily_bars_csv(path: Path) -> list[DailyBarDraft]:
    """Load and validate daily bars from a local CSV file."""
    if not path.is_file():
        raise CsvLoadError(f"CSV file not found: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise CsvLoadError("CSV has no header row")
        columns = [name.strip() for name in reader.fieldnames]
        missing = [name for name in REQUIRED_COLUMNS if name not in columns]
        if missing:
            raise CsvLoadError(f"CSV missing required columns: {missing}")
        drafts: list[DailyBarDraft] = []
        for row_number, row in enumerate(reader, start=2):
            try:
                volume_raw = row.get("volume")
                draft = DailyBarDraft(
                    symbol=str(row.get("symbol", "")),
                    observation_time=parse_observation_time(str(row.get("date", ""))),
                    available_time=parse_utc_datetime(
                        str(row.get("available_time", "")), field="available_time"
                    ),
                    open=parse_decimal(row.get("open"), field="open"),
                    high=parse_decimal(row.get("high"), field="high"),
                    low=parse_decimal(row.get("low"), field="low"),
                    close=parse_decimal(row.get("close"), field="close"),
                    volume=_optional_volume(volume_raw),
                )
                drafts.append(validate_daily_bar_draft(draft))
            except DataValidationError as exc:
                raise CsvLoadError(f"row {row_number}: {exc}") from exc
    if not drafts:
        raise CsvLoadError("CSV contains no data rows")
    return drafts
