"""Point-in-time and OHLC invariants for research observations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum


class IngestionErrorCode(StrEnum):
    VALIDATION_ERROR = "validation_error"
    NAIVE_TIMESTAMP = "naive_timestamp"
    LOOKAHEAD = "lookahead"
    INVALID_OHLC = "invalid_ohlc"
    INVALID_NUMBER = "invalid_number"
    EMPTY_SYMBOL = "empty_symbol"
    CSV_ERROR = "csv_error"
    FILE_NOT_FOUND = "file_not_found"
    MISSING_COLUMNS = "missing_columns"
    EMPTY_FILE = "empty_file"
    CLOSED_SESSION = "closed_session"
    INVALID_TIMEZONE = "invalid_timezone"
    STALE_CORRECTION = "stale_correction"
    UNKNOWN_EXCHANGE = "unknown_exchange"
    INVALID_NAMESPACE = "invalid_namespace"
    INVALID_ACTION_TYPE = "invalid_action_type"
    INVALID_SESSION_KIND = "invalid_session_kind"


class DataValidationError(ValueError):
    """Raised when a research observation violates ingestion rules."""

    def __init__(
        self, message: str, *, code: str = IngestionErrorCode.VALIDATION_ERROR
    ) -> None:
        super().__init__(message)
        self.code = code


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
        raise DataValidationError(msg, code=IngestionErrorCode.NAIVE_TIMESTAMP)
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
        raise DataValidationError(msg, code=IngestionErrorCode.LOOKAHEAD)


def parse_decimal(value: object, *, field: str) -> Decimal:
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError) as exc:
        msg = f"{field} is not a valid decimal: {value!r}"
        raise DataValidationError(msg, code=IngestionErrorCode.INVALID_NUMBER) from exc
    if not number.is_finite():
        msg = f"{field} must be finite, got {value!r}"
        raise DataValidationError(msg, code=IngestionErrorCode.INVALID_NUMBER)
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
            raise DataValidationError(msg, code=IngestionErrorCode.INVALID_OHLC)
    if volume is not None and volume < 0:
        msg = f"volume must be non-negative, got {volume}"
        raise DataValidationError(msg, code=IngestionErrorCode.INVALID_OHLC)
    if high < low:
        msg = f"high must be >= low (high={high}, low={low})"
        raise DataValidationError(msg, code=IngestionErrorCode.INVALID_OHLC)
    if high < open_ or high < close:
        msg = (
            f"high must be >= open and close (open={open_}, high={high}, close={close})"
        )
        raise DataValidationError(msg, code=IngestionErrorCode.INVALID_OHLC)
    if low > open_ or low > close:
        msg = f"low must be <= open and close (open={open_}, low={low}, close={close})"
        raise DataValidationError(msg, code=IngestionErrorCode.INVALID_OHLC)


def validate_daily_bar_draft(draft: DailyBarDraft) -> DailyBarDraft:
    if not draft.symbol.strip():
        raise DataValidationError(
            "symbol must not be empty", code=IngestionErrorCode.EMPTY_SYMBOL
        )
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
