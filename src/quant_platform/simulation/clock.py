"""Deterministic simulation clock. UTC only; no wall-clock scheduling."""

from __future__ import annotations

from datetime import datetime

from quant_platform.data.validation import DataValidationError, ensure_utc
from quant_platform.simulation.errors import SimulationError, SimulationErrorCode


class SimulationClock:
    """Monotonic UTC cursor over a replay timeline."""

    def __init__(self, *, current_time: datetime | None = None) -> None:
        self._current: datetime | None = (
            None if current_time is None else _utc(current_time, field="current_time")
        )

    @property
    def current_time(self) -> datetime | None:
        return self._current

    def advance_to(self, when: datetime) -> datetime:
        """Move forward to ``when``. Equal timestamps are allowed; going back is not."""
        instant = _utc(when, field="when")
        if self._current is not None and instant < self._current:
            raise SimulationError(
                "simulation clock cannot move backwards "
                f"({instant.isoformat()} < {self._current.isoformat()})",
                code=SimulationErrorCode.CLOCK_REGRESSION,
            )
        self._current = instant
        return instant


def _utc(value: datetime, *, field: str) -> datetime:
    try:
        return ensure_utc(value, field=field)
    except DataValidationError as exc:
        raise SimulationError(
            str(exc), code=SimulationErrorCode.NAIVE_TIMESTAMP
        ) from exc
