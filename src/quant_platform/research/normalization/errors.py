"""Normalization errors. Not a trading or strategy failure."""

from __future__ import annotations

from enum import StrEnum


class NormalizationErrorCode(StrEnum):
    MISSING_AS_OF = "missing_as_of"
    NAIVE_TIMESTAMP = "naive_timestamp"
    INVALID_RANGE = "invalid_range"
    EMPTY_FILTER = "empty_filter"
    MISSING_SOURCE = "missing_source"
    INVALID_MODE = "invalid_mode"
    INVALID_RATIO = "invalid_split_ratio"
    SECRET_LIKE_VALUE = "secret_like_value"  # noqa: S105
    ARTIFACT_INVALID = "artifact_invalid"


class NormalizationError(ValueError):
    """Raised when a normalization request or artifact is invalid."""

    def __init__(
        self, message: str, *, code: str = NormalizationErrorCode.INVALID_RANGE
    ) -> None:
        super().__init__(message)
        self.code = code
