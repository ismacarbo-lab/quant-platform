"""Point-in-time and OHLC invariants for research observations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation


class DataValidationError(ValueError):
    """Raised when a research observation violates ingestion rules."""


@dataclass(frozen=True, slots=True)
class DailyBarDraft:
    """Validated daily OHLCV row before persistence."""

    symbol: str
    observation_time: datetime
    available_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None


def ensure_utc(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None:
        msg = f"{field} must be timezone-aware UTC, got naive {value!r}"
        raise DataValidationError(msg)
    return value.astimezone(UTC)


def require_available_after_observation(
    observation_time: datetime, available_time: datetime
) -> None:
    obs = ensure_utc(observation_time, field="observation_time")
    avail = ensure_utc(available_time, field="available_time")
    if not avail > obs:
        msg = (
            "available_time must be strictly after observation_time "
            f"(available_time={avail.isoformat()}, "
            f"observation_time={obs.isoformat()})"
        )
        raise DataValidationError(msg)


def parse_decimal(value: object, *, field: str) -> Decimal:
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError) as exc:
        msg = f"{field} is not a valid decimal: {value!r}"
        raise DataValidationError(msg) from exc
    if not number.is_finite():
        msg = f"{field} must be finite, got {value!r}"
        raise DataValidationError(msg)
    return number


def validate_ohlc(
    open_: Decimal,
    high: Decimal,
    low: Decimal,
    close: Decimal,
    volume: Decimal | None,
) -> None:
    for field, price in (
        ("open", open_),
        ("high", high),
        ("low", low),
        ("close", close),
    ):
        if price < 0:
            msg = f"{field} must be non-negative, got {price}"
            raise DataValidationError(msg)
    if volume is not None and volume < 0:
        msg = f"volume must be non-negative, got {volume}"
        raise DataValidationError(msg)
    if high < low:
        msg = f"high must be >= low (high={high}, low={low})"
        raise DataValidationError(msg)
    if high < open_ or high < close:
        msg = (
            f"high must be >= open and close (open={open_}, high={high}, close={close})"
        )
        raise DataValidationError(msg)
    if low > open_ or low > close:
        msg = f"low must be <= open and close (open={open_}, low={low}, close={close})"
        raise DataValidationError(msg)


def validate_daily_bar_draft(draft: DailyBarDraft) -> DailyBarDraft:
    if not draft.symbol.strip():
        raise DataValidationError("symbol must not be empty")
    observation = ensure_utc(draft.observation_time, field="observation_time")
    available = ensure_utc(draft.available_time, field="available_time")
    require_available_after_observation(observation, available)
    validate_ohlc(draft.open, draft.high, draft.low, draft.close, draft.volume)
    return DailyBarDraft(
        symbol=draft.symbol.strip(),
        observation_time=observation,
        available_time=available,
        open=draft.open,
        high=draft.high,
        low=draft.low,
        close=draft.close,
        volume=draft.volume,
    )
