"""Deterministic daily-bar replay. No strategies, signals, or trading."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from pathlib import Path
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from quant_platform.data.calendar import session_date_for_observation
from quant_platform.data.models import MarketCalendar, MarketSession
from quant_platform.data.repository import (
    get_market_calendar_by_code,
    list_market_sessions,
)
from quant_platform.data.validation import DataValidationError, ensure_utc
from quant_platform.research.catalog_integrity import (
    load_snapshot_daily_bar_rows,
    verify_snapshot_artifacts,
)
from quant_platform.research.datasets import (
    get_corporate_actions_for_dataset,
    get_daily_bars_dataset,
)
from quant_platform.research.errors import DatasetErrorCode, DatasetValidationError
from quant_platform.research.snapshot_types import (
    DAILY_BARS_ARTIFACT_NAME,
    MANIFEST_ARTIFACT_NAME,
)
from quant_platform.research.snapshots import hash_daily_bars_dataset
from quant_platform.research.types import (
    CorporateActionDatasetRow,
    DailyBarDatasetRow,
    DailyBarsDataset,
    DailyBarsDatasetRequest,
    build_daily_bars_dataset_request,
)
from quant_platform.simulation.clock import SimulationClock
from quant_platform.simulation.errors import SimulationError, SimulationErrorCode
from quant_platform.simulation.events import (
    CorporateActionEvent,
    MarketBarEvent,
    MarketSessionEvent,
    ReplayEvent,
    ReplayFinishedEvent,
    ReplayStartedEvent,
    corporate_action_event_from_row,
    market_bar_event_from_row,
    replay_event_sort_key,
)
from quant_platform.simulation.hashing import (
    derive_replay_id,
    hash_replay_events,
    hash_replay_request,
)
from quant_platform.simulation.summary import (
    SOURCE_DATABASE,
    SOURCE_SNAPSHOT,
    ReplaySummary,
)

_SNAPSHOT_CA_WARNING = (
    "include_corporate_actions is ignored for snapshot replay; "
    "snapshots do not store corporate-action rows"
)
_SNAPSHOT_SESSION_WARNING = (
    "include_sessions is ignored for snapshot replay; "
    "snapshots do not store calendar sessions"
)


@dataclass(frozen=True, slots=True)
class DailyBarReplay:
    """Immutable replay: started, payload events, finished."""

    events: tuple[ReplayEvent, ...]
    summary: ReplaySummary

    def __iter__(self) -> Iterator[ReplayEvent]:
        return iter(self.events)

    def __len__(self) -> int:
        return len(self.events)

    @property
    def bars(self) -> tuple[MarketBarEvent, ...]:
        return tuple(
            event for event in self.events if isinstance(event, MarketBarEvent)
        )

    @property
    def sessions(self) -> tuple[MarketSessionEvent, ...]:
        return tuple(
            event for event in self.events if isinstance(event, MarketSessionEvent)
        )

    @property
    def corporate_actions(self) -> tuple[CorporateActionEvent, ...]:
        return tuple(
            event for event in self.events if isinstance(event, CorporateActionEvent)
        )


def replay_daily_bars_dataset(
    dataset: DailyBarsDataset,
    *,
    replay_id: UUID | None = None,
    source_type: str = SOURCE_DATABASE,
    content_hash: str | None = None,
    warnings: Sequence[str] = (),
    corporate_actions: Sequence[CorporateActionDatasetRow] = (),
    session_events: Sequence[MarketSessionEvent] = (),
    include_corporate_actions: bool = False,
    include_sessions: bool = False,
    deterministic_id: bool = False,
) -> DailyBarReplay:
    """Emit a deterministic event stream from an in-memory PIT dataset.

    ``event_time`` for each bar and corporate action is ``available_time`` so a
    consumer never sees a fact before it was knowable. Dataset sort
    (observation time) is not the replay order.

    ``include_corporate_actions`` and ``include_sessions`` default to False so
    a bar-only stream stays compatible with Phase 3.0. Pass True for an
    audited stream. Session rows are local calendar facts, not PIT quotes.
    """
    request = dataset.request
    as_of = _utc(request.as_of, field="as_of")
    start_time = _utc(request.start_time, field="start_time")
    end_time = _utc(request.end_time, field="end_time")
    bars = tuple(_bar_event(row, as_of=as_of) for row in dataset.rows)
    actions: tuple[CorporateActionEvent, ...] = ()
    if include_corporate_actions:
        actions = tuple(
            _corporate_action_event(row, as_of=as_of) for row in corporate_actions
        )
    sessions: tuple[MarketSessionEvent, ...] = ()
    if include_sessions:
        sessions = tuple(_session_event(event, as_of=as_of) for event in session_events)
    payload: tuple[ReplayEvent, ...] = (*sessions, *actions, *bars)
    instrument_ids = {event.instrument_id for event in bars}
    if include_corporate_actions:
        instrument_ids.update(event.instrument_id for event in actions)
    instrument_count = len(instrument_ids)
    payload_times = [event.event_time for event in payload]
    finished_at = end_time
    if payload_times:
        finished_at = max(finished_at, max(payload_times))
    if finished_at < start_time:
        finished_at = start_time
    event_count = len(payload) + 2
    started = ReplayStartedEvent(
        event_time=start_time,
        start_time=start_time,
        end_time=end_time,
        as_of=as_of,
        instrument_count=instrument_count,
    )
    finished = ReplayFinishedEvent(
        event_time=finished_at,
        started_at=start_time,
        finished_at=finished_at,
        event_count=event_count,
        bar_count=len(bars),
        instrument_count=instrument_count,
    )
    events = tuple(sorted((started, *payload, finished), key=replay_event_sort_key))
    clock = SimulationClock()
    for event in events:
        clock.advance_to(event.event_time)
    digest = (
        content_hash if content_hash is not None else hash_daily_bars_dataset(dataset)
    )
    stream_hash = hash_replay_events(events)
    resolved_id = replay_id
    if resolved_id is None and deterministic_id:
        resolved_id = derive_replay_id(stream_hash, hash_replay_request(request))
    if resolved_id is None:
        resolved_id = uuid4()
    first_payload: datetime | None = None
    last_payload: datetime | None = None
    ordered_payload = tuple(
        event
        for event in events
        if not isinstance(event, ReplayStartedEvent | ReplayFinishedEvent)
    )
    if ordered_payload:
        first_payload = ordered_payload[0].event_time
        last_payload = ordered_payload[-1].event_time
    summary = ReplaySummary(
        replay_id=resolved_id,
        started_at=start_time,
        finished_at=finished_at,
        start_time=start_time,
        end_time=end_time,
        as_of=as_of,
        event_count=event_count,
        bar_count=len(bars),
        session_count=len(sessions),
        corporate_action_count=len(actions),
        instrument_count=instrument_count,
        first_event_time=first_payload,
        last_event_time=last_payload,
        content_hash=digest,
        stream_hash=stream_hash,
        source_type=source_type,
        warnings=tuple(warnings),
    )
    return DailyBarReplay(events=events, summary=summary)


def create_daily_bar_replay(
    session: Session,
    request: DailyBarsDatasetRequest,
    *,
    replay_id: UUID | None = None,
    include_corporate_actions: bool = False,
    include_sessions: bool = False,
    deterministic_id: bool = False,
) -> DailyBarReplay:
    """Load a PIT dataset from PostgreSQL and replay it."""
    dataset = get_daily_bars_dataset(session, request)
    actions: tuple[CorporateActionDatasetRow, ...] = ()
    if include_corporate_actions:
        actions = get_corporate_actions_for_dataset(session, request)
    sessions: tuple[MarketSessionEvent, ...] = ()
    if include_sessions:
        sessions = _session_events_for_request(session, request)
    return replay_daily_bars_dataset(
        dataset,
        replay_id=replay_id,
        source_type=SOURCE_DATABASE,
        corporate_actions=actions,
        session_events=sessions,
        include_corporate_actions=include_corporate_actions,
        include_sessions=include_sessions,
        deterministic_id=deterministic_id,
    )


def replay_daily_bars_snapshot(
    snapshot_dir: Path | str,
    *,
    replay_id: UUID | None = None,
    include_corporate_actions: bool = False,
    include_sessions: bool = False,
    deterministic_id: bool = False,
) -> DailyBarReplay:
    """Replay a local snapshot folder. Does not query PostgreSQL."""
    root = Path(snapshot_dir)
    report = verify_snapshot_artifacts(root)
    if not report.ok:
        codes = ",".join(
            sorted({issue.code for issue in report.issues if issue.severity == "error"})
        )
        raise SimulationError(
            f"snapshot failed integrity checks ({codes})",
            code=SimulationErrorCode.BROKEN_SNAPSHOT,
        )
    manifest_path = root / MANIFEST_ARTIFACT_NAME
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SimulationError(
            "manifest.json is not valid JSON",
            code=SimulationErrorCode.BROKEN_SNAPSHOT,
        ) from exc
    if not isinstance(payload, dict):
        raise SimulationError(
            "manifest.json must be an object",
            code=SimulationErrorCode.BROKEN_SNAPSHOT,
        )
    request = _request_from_manifest(payload)
    rows = load_snapshot_daily_bar_rows(root / DAILY_BARS_ARTIFACT_NAME)
    dataset = DailyBarsDataset(request=request, rows=rows)
    stored_hash = payload.get("content_hash")
    content_hash = stored_hash if isinstance(stored_hash, str) else None
    notes: list[str] = []
    if include_corporate_actions:
        notes.append(_SNAPSHOT_CA_WARNING)
    if include_sessions:
        notes.append(_SNAPSHOT_SESSION_WARNING)
    return replay_daily_bars_dataset(
        dataset,
        replay_id=replay_id,
        source_type=SOURCE_SNAPSHOT,
        content_hash=content_hash,
        warnings=notes,
        include_corporate_actions=False,
        include_sessions=False,
        deterministic_id=deterministic_id,
    )


def _bar_event(row: DailyBarDatasetRow, *, as_of: datetime) -> MarketBarEvent:
    event = market_bar_event_from_row(row)
    if event.available_time > as_of:
        raise SimulationError(
            "available_time must be <= as_of",
            code=SimulationErrorCode.LOOKAHEAD,
        )
    return event


def _corporate_action_event(
    row: CorporateActionDatasetRow, *, as_of: datetime
) -> CorporateActionEvent:
    event = corporate_action_event_from_row(row)
    if event.available_time > as_of:
        raise SimulationError(
            "corporate action available_time must be <= as_of",
            code=SimulationErrorCode.LOOKAHEAD,
        )
    return event


def _session_event(event: MarketSessionEvent, *, as_of: datetime) -> MarketSessionEvent:
    instant = _utc(event.event_time, field="event_time")
    if instant > as_of:
        raise SimulationError(
            "session event_time must be <= as_of",
            code=SimulationErrorCode.LOOKAHEAD,
        )
    return event


def _session_events_for_request(
    session: Session, request: DailyBarsDatasetRequest
) -> tuple[MarketSessionEvent, ...]:
    if request.calendar_code is None:
        return ()
    calendar = get_market_calendar_by_code(session, code=request.calendar_code)
    if calendar is None:
        raise DatasetValidationError(
            f"unknown calendar {request.calendar_code!r}",
            code=DatasetErrorCode.UNKNOWN_CALENDAR,
        )
    start_day = session_date_for_observation(request.start_time, calendar.timezone)
    end_day = session_date_for_observation(request.end_time, calendar.timezone)
    as_of = _utc(request.as_of, field="as_of")
    events: list[MarketSessionEvent] = []
    for row in list_market_sessions(session, calendar_id=calendar.id):
        if row.session_date < start_day or row.session_date > end_day:
            continue
        built = _market_session_event(row, calendar=calendar)
        if built.event_time > as_of:
            continue
        events.append(built)
    return tuple(events)


def _market_session_event(
    row: MarketSession, *, calendar: MarketCalendar
) -> MarketSessionEvent:
    event_time = _session_event_time(
        session_date=row.session_date,
        open_time=row.open_time,
        timezone_name=calendar.timezone,
    )
    return MarketSessionEvent(
        event_time=event_time,
        session_date=row.session_date,
        calendar_code=calendar.code,
        exchange_code=None,
        session_kind=row.session_kind,
        is_open=row.is_open,
        open_time=row.open_time,
        close_time=row.close_time,
        note=row.note,
    )


def _session_event_time(
    *,
    session_date: date,
    open_time: time | None,
    timezone_name: str,
) -> datetime:
    clock = open_time if open_time is not None else time(0, 0)
    if clock.tzinfo is not None:
        clock = clock.replace(tzinfo=None)
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise SimulationError(
            f"unknown calendar timezone {timezone_name!r}",
            code=SimulationErrorCode.INVALID_EVENT_TIME,
        ) from exc
    local = datetime.combine(session_date, clock, tzinfo=zone)
    return local.astimezone(UTC)


def _utc(value: datetime, *, field: str) -> datetime:
    try:
        return ensure_utc(value, field=field)
    except DataValidationError as exc:
        raise SimulationError(
            str(exc), code=SimulationErrorCode.NAIVE_TIMESTAMP
        ) from exc


def _request_from_manifest(payload: Mapping[str, object]) -> DailyBarsDatasetRequest:
    raw = payload.get("dataset_request")
    if not isinstance(raw, dict):
        raise SimulationError(
            "manifest dataset_request is missing",
            code=SimulationErrorCode.BROKEN_SNAPSHOT,
        )
    try:
        return build_daily_bars_dataset_request(
            as_of=_parse_manifest_time(raw.get("as_of"), field="as_of"),
            start_time=_parse_manifest_time(raw.get("start_time"), field="start_time"),
            end_time=_parse_manifest_time(raw.get("end_time"), field="end_time"),
            symbols=_optional_str_list(raw.get("symbols")),
            instrument_ids=_optional_uuid_list(raw.get("instrument_ids")),
            exchange_codes=_optional_str_list(raw.get("exchange_codes")),
            asset_classes=_optional_str_list(raw.get("asset_classes")),
            currency=_optional_str(raw.get("currency")),
            calendar_code=_optional_str(raw.get("calendar_code")),
            require_open_session=bool(raw.get("require_open_session", False)),
            allow_unfiltered=bool(raw.get("allow_unfiltered", False)),
        )
    except DatasetValidationError as exc:
        raise SimulationError(
            str(exc), code=SimulationErrorCode.BROKEN_SNAPSHOT
        ) from exc


def _parse_manifest_time(value: object, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise SimulationError(
            f"manifest {field} is required",
            code=SimulationErrorCode.BROKEN_SNAPSHOT,
        )
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    return _utc(parsed, field=field)


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SimulationError(
            "manifest string field has the wrong type",
            code=SimulationErrorCode.BROKEN_SNAPSHOT,
        )
    stripped = value.strip()
    return stripped or None


def _optional_str_list(value: object) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise SimulationError(
            "manifest list field has the wrong type",
            code=SimulationErrorCode.BROKEN_SNAPSHOT,
        )
    items: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise SimulationError(
                "manifest list field has the wrong type",
                code=SimulationErrorCode.BROKEN_SNAPSHOT,
            )
        items.append(item)
    return items


def _optional_uuid_list(value: object) -> list[UUID] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise SimulationError(
            "manifest instrument_ids has the wrong type",
            code=SimulationErrorCode.BROKEN_SNAPSHOT,
        )
    try:
        return [UUID(str(item)) for item in value]
    except (TypeError, ValueError) as exc:
        raise SimulationError(
            "manifest instrument_ids has the wrong type",
            code=SimulationErrorCode.BROKEN_SNAPSHOT,
        ) from exc
