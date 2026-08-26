"""Backtest errors. Distinct from ingestion, dataset, and simulation errors."""

from __future__ import annotations

from enum import StrEnum


class BacktestErrorCode(StrEnum):
    NAIVE_TIMESTAMP = "naive_timestamp"
    NOT_READY = "not_ready"
    CATALOG_INVALID = "catalog_invalid"
    CATALOG_CONFLICT = "catalog_conflict"
    BROKEN_RUN = "broken_run"
    INVALID_POLICY = "invalid_policy"
    APP_MODE_NOT_RESEARCH = "app_mode_not_research"


class BacktestError(ValueError):
    """Raised when a dry-run backtest cannot start or be catalogued."""

    def __init__(
        self, message: str, *, code: str = BacktestErrorCode.CATALOG_INVALID
    ) -> None:
        super().__init__(message)
        self.code = code
