"""Load small local research fixtures from CSV. No vendor downloads."""

from __future__ import annotations

import csv
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path

from sqlalchemy.orm import Session

from quant_platform.data.repository import (
    create_corporate_action,
    create_exchange,
    create_session,
    upsert_instrument,
    upsert_market_calendar,
)
from quant_platform.data.validation import DataValidationError, IngestionErrorCode


def _blank(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _parse_date(value: str) -> date:
    return date.fromisoformat(value.strip())


def _parse_time(value: str | None) -> time | None:
    raw = _blank(value)
    if raw is None:
        return None
    return time.fromisoformat(raw)


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))


def _parse_decimal(value: str | None) -> Decimal | None:
    raw = _blank(value)
    if raw is None:
        return None
    return Decimal(raw)


def load_exchanges_csv(session: Session, path: Path) -> int:
    count = 0
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            create_exchange(
                session,
                code=row["code"],
                timezone=row["timezone"],
                mic=_blank(row.get("mic")),
                country=_blank(row.get("country")),
                currency=_blank(row.get("currency")),
            )
            count += 1
    return count


def load_calendars_csv(session: Session, path: Path) -> int:
    count = 0
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            upsert_market_calendar(
                session,
                code=row["code"],
                name=row["name"],
                timezone=row["timezone"],
            )
            count += 1
    return count


def load_sessions_csv(session: Session, path: Path) -> int:
    count = 0
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            calendar = upsert_market_calendar(
                session,
                code=row["calendar_code"],
                name=row.get("calendar_name") or row["calendar_code"],
                timezone=row.get("calendar_timezone") or "UTC",
            )
            create_session(
                session,
                calendar_id=calendar.id,
                session_date=_parse_date(row["session_date"]),
                session_kind=row["session_kind"],
                open_time=_parse_time(row.get("open_time")),
                close_time=_parse_time(row.get("close_time")),
                note=_blank(row.get("note")),
            )
            count += 1
    return count


def load_corporate_actions_csv(session: Session, path: Path) -> int:
    count = 0
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            exchange_code = _blank(row.get("exchange_code"))
            if exchange_code is None:
                raise DataValidationError(
                    "corporate action CSV requires exchange_code",
                    code=IngestionErrorCode.UNKNOWN_EXCHANGE,
                )
            create_exchange(
                session,
                code=exchange_code,
                timezone=row.get("exchange_timezone") or "UTC",
            )
            instrument = upsert_instrument(
                session,
                symbol=row["symbol"],
                asset_class=row["asset_class"],
                currency=_blank(row.get("currency")),
                exchange=exchange_code,
            )
            create_corporate_action(
                session,
                instrument_id=instrument.id,
                action_type=row["action_type"],
                effective_time=_parse_datetime(row["effective_time"]),
                available_time=_parse_datetime(row["available_time"]),
                quantity_before=_parse_decimal(row.get("quantity_before")),
                quantity_after=_parse_decimal(row.get("quantity_after")),
                cash_amount=_parse_decimal(row.get("cash_amount")),
                currency=_blank(row.get("currency")),
                old_value=_blank(row.get("old_value")),
                new_value=_blank(row.get("new_value")),
                note=_blank(row.get("note")),
            )
            count += 1
    return count
