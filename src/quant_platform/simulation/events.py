"""Typed replay events. Market data only; no orders, signals, or portfolio."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from quant_platform.data.validation import DataValidationError, ensure_utc
from quant_platform.research.types import DailyBarDatasetRow
from quant_platform.simulation.errors import SimulationError, SimulationErrorCode

REPLAY_STARTED_KIND = "replay_started"
MARKET_BAR_KIND = "market_bar"
REPLAY_FINISHED_KIND = "replay_finished"


def _utc(value: datetime, *, field: str) -> datetime:
    try:
        return ensure_utc(value, field=field)
    except DataValidationError as exc:
        raise SimulationError(
            str(exc), code=SimulationErrorCode.NAIVE_TIMESTAMP
        ) from exc


def _fmt_decimal(value: Decimal | None) -> str:
    if value is None:
        return ""
    return format(value, "f")


@dataclass(frozen=True, slots=True)
class ReplayStartedEvent:
    event_time: datetime
    start_time: datetime
    end_time: datetime
    as_of: datetime
    instrument_count: int

    @property
    def kind(self) -> str:
        return REPLAY_STARTED_KIND

    def as_mapping(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "event_time": self.event_time.isoformat(),
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "as_of": self.as_of.isoformat(),
            "instrument_count": self.instrument_count,
        }


@dataclass(frozen=True, slots=True)
class MarketBarEvent:
    """One PIT-visible daily bar. ``event_time`` is ``available_time``."""

    event_time: datetime
    observation_time: datetime
    available_time: datetime
    instrument_id: UUID
    symbol: str
    exchange_code: str | None
    asset_class: str
    currency: str | None
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None
    source_name: str
    is_correction: bool
    correction_reason: str | None

    def __post_init__(self) -> None:
        if self.event_time != self.available_time:
            raise SimulationError(
                "bar event_time must equal available_time",
                code=SimulationErrorCode.INVALID_EVENT_TIME,
            )

    @property
    def kind(self) -> str:
        return MARKET_BAR_KIND

    def as_mapping(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "event_time": self.event_time.isoformat(),
            "observation_time": self.observation_time.isoformat(),
            "available_time": self.available_time.isoformat(),
            "instrument_id": str(self.instrument_id),
            "symbol": self.symbol,
            "exchange_code": self.exchange_code,
            "asset_class": self.asset_class,
            "currency": self.currency,
            "open": _fmt_decimal(self.open),
            "high": _fmt_decimal(self.high),
            "low": _fmt_decimal(self.low),
            "close": _fmt_decimal(self.close),
            "volume": _fmt_decimal(self.volume),
            "source_name": self.source_name,
            "is_correction": self.is_correction,
            "correction_reason": self.correction_reason,
        }


@dataclass(frozen=True, slots=True)
class ReplayFinishedEvent:
    event_time: datetime
    started_at: datetime
    finished_at: datetime
    event_count: int
    bar_count: int
    instrument_count: int

    @property
    def kind(self) -> str:
        return REPLAY_FINISHED_KIND

    def as_mapping(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "event_time": self.event_time.isoformat(),
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "event_count": self.event_count,
            "bar_count": self.bar_count,
            "instrument_count": self.instrument_count,
        }


ReplayEvent = ReplayStartedEvent | MarketBarEvent | ReplayFinishedEvent


def market_bar_event_from_row(row: DailyBarDatasetRow) -> MarketBarEvent:
    """Build a bar event. ``event_time`` is always ``available_time``."""
    observation = _utc(row.observation_time, field="observation_time")
    available = _utc(row.available_time, field="available_time")
    return MarketBarEvent(
        event_time=available,
        observation_time=observation,
        available_time=available,
        instrument_id=row.instrument_id,
        symbol=row.symbol,
        exchange_code=row.exchange_code,
        asset_class=row.asset_class,
        currency=row.currency,
        open=row.open,
        high=row.high,
        low=row.low,
        close=row.close,
        volume=row.volume,
        source_name=row.source_name,
        is_correction=row.is_correction,
        correction_reason=row.correction_reason,
    )
