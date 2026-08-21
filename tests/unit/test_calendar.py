"""Manual calendar date helpers without a database."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from quant_platform.data.calendar import session_date_for_observation
from quant_platform.data.validation import DataValidationError


def test_session_date_uses_calendar_timezone() -> None:
    # 2024-01-02 04:00 UTC is still 2024-01-01 in America/New_York.
    observation = datetime(2024, 1, 2, 4, 0, tzinfo=UTC)
    ny = session_date_for_observation(observation, "America/New_York")
    utc_date = session_date_for_observation(observation, "UTC")
    assert utc_date.isoformat() == "2024-01-02"
    assert ny.isoformat() == "2024-01-01"
    assert ZoneInfo("America/New_York") is not None


def test_session_date_rejects_naive_datetime() -> None:
    with pytest.raises(DataValidationError, match="timezone-aware"):
        session_date_for_observation(datetime(2024, 1, 2), "UTC")


def test_session_date_rejects_unknown_timezone() -> None:
    with pytest.raises(DataValidationError, match="unknown calendar timezone"):
        session_date_for_observation(datetime(2024, 1, 2, tzinfo=UTC), "Not/AZone")
