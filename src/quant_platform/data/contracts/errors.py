"""Vendor-agnostic contract errors. Not a broker, download, or trading failure."""

from __future__ import annotations

from enum import StrEnum


class VendorContractErrorCode(StrEnum):
    VALIDATION_ERROR = "validation_error"
    EMPTY_SYMBOL = "empty_symbol"
    EMPTY_SOURCE_NAME = "empty_source_name"
    NAIVE_TIMESTAMP = "naive_timestamp"
    LOOKAHEAD = "lookahead"
    INVALID_OHLC = "invalid_ohlc"
    INVALID_NUMBER = "invalid_number"
    MISSING_EFFECTIVE_TIME = "missing_effective_time"
    MISSING_SESSION_DATE = "missing_session_date"
    SECRET_IN_METADATA = "secret_in_metadata"  # noqa: S105
    TOKEN_URL = "token_url"  # noqa: S105
    FORBIDDEN_TERM = "forbidden_term"
    REAL_VENDOR_NAME = "real_vendor_name"
    NETWORK_REQUIRED = "network_required"
    CREDENTIALS_REQUIRED = "credentials_required"
    PIT_NOT_REQUIRED = "pit_not_required"
    INVALID_SOURCE_KIND = "invalid_source_kind"
    INVALID_ACTION_TYPE = "invalid_action_type"
    INVALID_SESSION_KIND = "invalid_session_kind"
    FIXTURE_UNREADABLE = "fixture_unreadable"
    NETWORKING_IMPORT = "networking_import"
    WRITE_DB_REQUIRED = "write_db_required"


class VendorContractError(ValueError):
    """Raised when a vendor-agnostic contract or fake payload is invalid."""

    def __init__(
        self,
        message: str,
        *,
        code: str = VendorContractErrorCode.VALIDATION_ERROR,
    ) -> None:
        super().__init__(message)
        self.code = code
