"""Dataset query errors. Separate from ingestion so callers can tell them apart."""

from __future__ import annotations

from enum import StrEnum


class DatasetErrorCode(StrEnum):
    MISSING_AS_OF = "missing_as_of"
    NAIVE_TIMESTAMP = "naive_timestamp"
    INVALID_RANGE = "invalid_range"
    UNBOUNDED_QUERY = "unbounded_query"
    EMPTY_FILTER = "empty_filter"
    CALENDAR_REQUIRED = "calendar_required"
    UNKNOWN_CALENDAR = "unknown_calendar"
    INCOMPLETE_CALENDAR = "incomplete_calendar"
    LOOKAHEAD = "lookahead"
    OUT_OF_RANGE = "out_of_range"
    INVALID_OHLC = "invalid_ohlc"
    CLOSED_SESSION = "closed_session"


class DatasetValidationError(ValueError):
    """Raised when a dataset request or result violates research rules."""

    def __init__(
        self, message: str, *, code: str = DatasetErrorCode.INVALID_RANGE
    ) -> None:
        super().__init__(message)
        self.code = code
