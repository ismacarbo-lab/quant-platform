"""Typed replay events. Market data only; no orders, signals, or portfolio."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID

from quant_platform.data.validation import DataValidationError, ensure_utc
from quant_platform.research.types import CorporateActionDatasetRow, DailyBarDatasetRow
from quant_platform.simulation.errors import SimulationError, SimulationErrorCode

REPLAY_STARTED_KIND = "replay_started"
MARKET_SESSION_KIND = "market_session"
CORPORATE_ACTION_KIND = "corporate_action"
MARKET_BAR_KIND = "market_bar"
REPLAY_FINISHED_KIND = "replay_finished"

# Lower sorts first when event_time ties inside the same boundary group.
EVENT_PRIORITY: dict[str, int] = {
    REPLAY_STARTED_KIND: 0,
    MARKET_SESSION_KIND: 1,
    CORPORATE_ACTION_KIND: 2,
    MARKET_BAR_KIND: 3,
    REPLAY_FINISHED_KIND: 4,
}

BOUNDARY_STARTED = 0
BOUNDARY_PREKNOWN = 1
BOUNDARY_WINDOW = 2
BOUNDARY_FINISHED = 3


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


def _fmt_time(value: time | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _corporate_action_value(row: CorporateActionDatasetRow) -> str | None:
    if row.cash_amount is not None:
        return format(row.cash_amount, "f")
    if row.new_value:
        return row.new_value
    if row.quantity_before is not None and row.quantity_after is not None:
        return f"{format(row.quantity_before, 'f')}:{format(row.quantity_after, 'f')}"
    return None


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
class MarketSessionEvent:
    """Local calendar row. Not a PIT market-data observation."""

    event_time: datetime
    session_date: date
    calendar_code: str
    exchange_code: str | None
    session_kind: str
    is_open: bool
    open_time: time | None
    close_time: time | None
    note: str | None
    known_before_start: bool = False

    @property
    def kind(self) -> str:
        return MARKET_SESSION_KIND

    def as_mapping(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "event_time": self.event_time.isoformat(),
            "session_date": self.session_date.isoformat(),
            "calendar_code": self.calendar_code,
            "exchange_code": self.exchange_code,
            "session_kind": self.session_kind,
            "is_open": self.is_open,
            "open_time": _fmt_time(self.open_time),
            "close_time": _fmt_time(self.close_time),
            "note": self.note,
            "known_before_start": self.known_before_start,
        }


@dataclass(frozen=True, slots=True)
class CorporateActionEvent:
    """Stored corporate action. OHLCV is never adjusted."""

    event_time: datetime
    effective_time: datetime
    available_time: datetime
    instrument_id: UUID
    symbol: str
    exchange_code: str | None
    action_type: str
    value: str | None
    currency: str | None
    description: str | None
    known_before_start: bool = False

    def __post_init__(self) -> None:
        if self.known_before_start:
            if self.event_time < self.available_time:
                raise SimulationError(
                    "pre-known corporate action event_time must be >= available_time",
                    code=SimulationErrorCode.INVALID_EVENT_TIME,
                )
            return
        if self.event_time != self.available_time:
            raise SimulationError(
                "corporate action event_time must equal available_time",
                code=SimulationErrorCode.INVALID_EVENT_TIME,
            )

    @property
    def kind(self) -> str:
        return CORPORATE_ACTION_KIND

    def as_mapping(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "event_time": self.event_time.isoformat(),
            "effective_time": self.effective_time.isoformat(),
            "available_time": self.available_time.isoformat(),
            "instrument_id": str(self.instrument_id),
            "symbol": self.symbol,
            "exchange_code": self.exchange_code,
            "action_type": self.action_type,
            "value": self.value,
            "currency": self.currency,
            "description": self.description,
            "known_before_start": self.known_before_start,
        }


@dataclass(frozen=True, slots=True)
class MarketBarEvent:
    """One PIT-visible daily bar.

    In-window ``event_time`` is ``available_time``. Pre-known bars clamp
    ``event_time`` to ``start_time``.
    """

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
    known_before_start: bool = False

    def __post_init__(self) -> None:
        if self.known_before_start:
            if self.event_time < self.available_time:
                raise SimulationError(
                    "pre-known bar event_time must be >= available_time",
                    code=SimulationErrorCode.INVALID_EVENT_TIME,
                )
            return
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
            "known_before_start": self.known_before_start,
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


ReplayEvent = (
    ReplayStartedEvent
    | MarketSessionEvent
    | CorporateActionEvent
    | MarketBarEvent
    | ReplayFinishedEvent
)


def is_pre_known_event(event: ReplayEvent) -> bool:
    return bool(getattr(event, "known_before_start", False))


def replay_boundary_group(event: ReplayEvent) -> int:
    """Bookend groups: started, pre-known, in-window, finished."""
    if isinstance(event, ReplayStartedEvent):
        return BOUNDARY_STARTED
    if isinstance(event, ReplayFinishedEvent):
        return BOUNDARY_FINISHED
    if is_pre_known_event(event):
        return BOUNDARY_PREKNOWN
    return BOUNDARY_WINDOW


def replay_event_sort_key(event: ReplayEvent) -> tuple[object, ...]:
    """Stable stream order with ReplayStarted first and ReplayFinished last."""
    group = replay_boundary_group(event)
    priority = EVENT_PRIORITY[event.kind]
    if isinstance(event, MarketBarEvent):
        return (
            group,
            event.event_time,
            priority,
            event.symbol,
            event.observation_time,
            event.source_name,
            str(event.instrument_id),
        )
    if isinstance(event, CorporateActionEvent):
        return (
            group,
            event.event_time,
            priority,
            event.symbol,
            event.effective_time,
            event.action_type,
            str(event.instrument_id),
        )
    if isinstance(event, MarketSessionEvent):
        return (
            group,
            event.event_time,
            priority,
            event.calendar_code,
            event.session_date.isoformat(),
            event.session_kind,
            event.exchange_code or "",
        )
    if isinstance(event, ReplayStartedEvent):
        return (
            group,
            event.event_time,
            priority,
            "",
            event.start_time,
            REPLAY_STARTED_KIND,
            "",
        )
    return (
        group,
        event.event_time,
        priority,
        "",
        event.finished_at,
        REPLAY_FINISHED_KIND,
        "",
    )


def apply_start_boundary(event: ReplayEvent, start_time: datetime) -> ReplayEvent:
    """Clamp pre-window facts to ``start_time`` and mark ``known_before_start``.

    ``available_time`` (PIT) is unchanged. Simulation ``event_time`` never
    precedes ``ReplayStartedEvent``.
    """
    start = _utc(start_time, field="start_time")
    if isinstance(event, CorporateActionEvent):
        available = _utc(event.available_time, field="available_time")
        if available < start:
            return replace(event, event_time=start, known_before_start=True)
        return event
    if isinstance(event, MarketBarEvent):
        available = _utc(event.available_time, field="available_time")
        if available < start:
            return replace(event, event_time=start, known_before_start=True)
        return event
    if isinstance(event, MarketSessionEvent):
        native = _utc(event.event_time, field="event_time")
        if native < start:
            return replace(event, event_time=start, known_before_start=True)
        return event
    return event


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


def corporate_action_event_from_row(
    row: CorporateActionDatasetRow,
) -> CorporateActionEvent:
    """Build a CA event. ``event_time`` is always ``available_time``."""
    effective = _utc(row.effective_time, field="effective_time")
    available = _utc(row.available_time, field="available_time")
    return CorporateActionEvent(
        event_time=available,
        effective_time=effective,
        available_time=available,
        instrument_id=row.instrument_id,
        symbol=row.symbol,
        exchange_code=row.exchange_code,
        action_type=row.action_type,
        value=_corporate_action_value(row),
        currency=row.currency,
        description=row.note,
    )
