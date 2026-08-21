"""Manual research calendars. No exchange downloads."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from quant_platform.data.validation import DataValidationError, IngestionErrorCode


def session_date_for_observation(
    observation_time: datetime, timezone_name: str
) -> date:
    """Civil date of ``observation_time`` in the calendar timezone."""
    if observation_time.tzinfo is None:
        raise DataValidationError(
            "observation_time must be timezone-aware UTC",
            code=IngestionErrorCode.NAIVE_TIMESTAMP,
        )
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise DataValidationError(
            f"unknown calendar timezone {timezone_name!r}",
            code=IngestionErrorCode.INVALID_TIMEZONE,
        ) from exc
    return observation_time.astimezone(zone).date()
