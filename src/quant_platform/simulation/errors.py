"""Simulation errors. Distinct from ingestion and dataset query errors."""

from __future__ import annotations

from enum import StrEnum


class SimulationErrorCode(StrEnum):
    NAIVE_TIMESTAMP = "naive_timestamp"
    CLOCK_REGRESSION = "clock_regression"
    LOOKAHEAD = "lookahead"
    INVALID_EVENT_TIME = "invalid_event_time"
    BROKEN_SNAPSHOT = "broken_snapshot"
    CATALOG_INVALID = "catalog_invalid"
    CATALOG_CONFLICT = "catalog_conflict"
    BROKEN_RUN = "broken_run"


class SimulationError(ValueError):
    """Raised when a replay or simulation clock violates research rules."""

    def __init__(
        self, message: str, *, code: str = SimulationErrorCode.INVALID_EVENT_TIME
    ) -> None:
        super().__init__(message)
        self.code = code
