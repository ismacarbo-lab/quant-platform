"""Point-in-time and OHLC validation without a database."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from quant_platform.data.validation import (
    DailyBarDraft,
    DataValidationError,
    ensure_utc,
    require_available_after_observation,
    validate_daily_bar_draft,
)


def _draft(**overrides: object) -> DailyBarDraft:
    base = {
        "symbol": "FIXT",
        "observation_time": datetime(2024, 1, 2, tzinfo=UTC),
        "available_time": datetime(2024, 1, 3, tzinfo=UTC),
        "open": Decimal("10"),
        "high": Decimal("11"),
        "low": Decimal("9"),
        "close": Decimal("10.5"),
        "volume": Decimal("100"),
    }
    base.update(overrides)
    return DailyBarDraft(**base)  # type: ignore[arg-type]


def test_ensure_utc_rejects_naive_datetime() -> None:
    with pytest.raises(DataValidationError, match="timezone-aware"):
        ensure_utc(datetime(2024, 1, 2), field="observation_time")


def test_ensure_utc_normalizes_offset_to_utc() -> None:
    from datetime import timedelta, timezone

    offset = timezone(timedelta(hours=-5))
    converted = ensure_utc(datetime(2024, 1, 2, 19, 0, tzinfo=offset), field="t")
    assert converted.tzinfo is UTC
    assert converted.hour == 0


def test_rejects_available_time_not_after_observation() -> None:
    obs = datetime(2024, 1, 2, tzinfo=UTC)
    with pytest.raises(DataValidationError, match="strictly after"):
        require_available_after_observation(obs, obs)
    with pytest.raises(DataValidationError, match="strictly after"):
        require_available_after_observation(obs, datetime(2024, 1, 1, tzinfo=UTC))


def test_accepts_available_time_after_observation() -> None:
    require_available_after_observation(
        datetime(2024, 1, 2, tzinfo=UTC),
        datetime(2024, 1, 3, tzinfo=UTC),
    )


def test_rejects_negative_price() -> None:
    with pytest.raises(DataValidationError, match="non-negative"):
        validate_daily_bar_draft(_draft(open=Decimal("-1")))


def test_rejects_high_below_low() -> None:
    with pytest.raises(DataValidationError, match="high must be >= low"):
        validate_daily_bar_draft(_draft(high=Decimal("8"), low=Decimal("9")))


def test_rejects_high_below_close() -> None:
    with pytest.raises(DataValidationError, match="high must be >="):
        validate_daily_bar_draft(_draft(high=Decimal("10"), close=Decimal("10.5")))


def test_valid_draft_is_normalized_utc() -> None:
    result = validate_daily_bar_draft(_draft())
    assert result.observation_time.tzinfo is UTC
    assert result.available_time > result.observation_time
