"""Read-only audit of a replay event stream. Not a backtest report."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from itertools import pairwise

from quant_platform.research.errors import DatasetValidationError
from quant_platform.research.quality_types import jsonable
from quant_platform.simulation.errors import SimulationError
from quant_platform.simulation.events import (
    MARKET_BAR_KIND,
    CorporateActionEvent,
    MarketBarEvent,
    MarketSessionEvent,
    ReplayEvent,
    ReplayFinishedEvent,
    ReplayStartedEvent,
    is_pre_known_event,
    replay_event_sort_key,
)
from quant_platform.simulation.hashing import hash_replay_events


class ReplayAuditSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ReplayAuditCode(StrEnum):
    OUT_OF_ORDER = "out_of_order"
    NAIVE_TIMESTAMP = "naive_timestamp"
    LOOKAHEAD = "lookahead"
    BAR_EVENT_TIME_MISMATCH = "bar_event_time_mismatch"
    CORPORATE_ACTION_EVENT_TIME_MISMATCH = "corporate_action_event_time_mismatch"
    MISSING_STARTED = "missing_started"
    MISSING_FINISHED = "missing_finished"
    PREKNOWN_MISPLACED = "preknown_misplaced"
    PREKNOWN_UNMARKED = "preknown_unmarked"
    EVENT_BEFORE_START = "event_before_start"
    MISSING_SESSIONS = "missing_sessions"
    SESSIONS_WITHOUT_CALENDAR = "sessions_without_calendar"
    SESSION_DATE_GAP = "session_date_gap"
    BAR_WITHOUT_SESSION = "bar_without_session"


SEVERITY_RANK: dict[str, int] = {
    ReplayAuditSeverity.ERROR.value: 0,
    ReplayAuditSeverity.WARNING.value: 1,
    ReplayAuditSeverity.INFO.value: 2,
}

_UNHASHABLE_STREAM = "sha256:" + ("0" * 64)

_BOUNDARY_ERROR_CODES = frozenset(
    {
        ReplayAuditCode.MISSING_STARTED,
        ReplayAuditCode.MISSING_FINISHED,
        ReplayAuditCode.PREKNOWN_MISPLACED,
        ReplayAuditCode.PREKNOWN_UNMARKED,
        ReplayAuditCode.EVENT_BEFORE_START,
    }
)


@dataclass(frozen=True, slots=True)
class ReplayAuditIssue:
    severity: str
    code: str
    message: str
    event_index: int | None = None
    event_kind: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    def as_mapping(self) -> dict[str, object]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "event_index": self.event_index,
            "event_kind": self.event_kind,
            "metadata": jsonable(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class ReplayAuditReport:
    stream_hash: str
    event_count: int
    counts_by_kind: Mapping[str, int]
    first_event_time: datetime | None
    last_event_time: datetime | None
    starts_with_replay_started: bool
    ends_with_replay_finished: bool
    boundary_ok: bool
    pre_known_event_count: int
    error_count: int
    warning_count: int
    info_count: int
    issues: tuple[ReplayAuditIssue, ...]

    @property
    def ok(self) -> bool:
        return self.error_count == 0

    def as_mapping(self) -> dict[str, object]:
        counts = {key: self.counts_by_kind[key] for key in sorted(self.counts_by_kind)}
        boundary = {
            "starts_with_replay_started": self.starts_with_replay_started,
            "ends_with_replay_finished": self.ends_with_replay_finished,
            "ok": self.boundary_ok,
            "pre_known_event_count": self.pre_known_event_count,
        }
        return {
            "ok": self.ok,
            "stream_hash": self.stream_hash,
            "event_count": self.event_count,
            "counts_by_kind": counts,
            "first_event_time": _iso(self.first_event_time),
            "last_event_time": _iso(self.last_event_time),
            "starts_with_replay_started": self.starts_with_replay_started,
            "ends_with_replay_finished": self.ends_with_replay_finished,
            "boundary_ok": self.boundary_ok,
            "pre_known_event_count": self.pre_known_event_count,
            "boundary": boundary,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "info_count": self.info_count,
            "issues": [issue.as_mapping() for issue in self.issues],
        }


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def audit_replay(
    events: Sequence[ReplayEvent],
    *,
    as_of: datetime,
    sessions_requested: bool = False,
    calendar_code: str | None = None,
    start_time: datetime | None = None,
) -> ReplayAuditReport:
    """Diagnose stream order, PIT, and calendar coverage. Does not mutate events."""
    issues: list[ReplayAuditIssue] = []
    if as_of.tzinfo is None:
        issues.append(
            ReplayAuditIssue(
                severity=ReplayAuditSeverity.ERROR,
                code=ReplayAuditCode.NAIVE_TIMESTAMP,
                message="as_of must be timezone-aware UTC",
            )
        )
    if start_time is not None and start_time.tzinfo is None:
        issues.append(
            ReplayAuditIssue(
                severity=ReplayAuditSeverity.ERROR,
                code=ReplayAuditCode.NAIVE_TIMESTAMP,
                message="start_time must be timezone-aware UTC",
            )
        )
    resolved_start = _resolved_start_time(events, start_time)
    for index, event in enumerate(events):
        issues.extend(_event_issues(event, index=index, as_of=as_of))
    issues.extend(_order_issues(events))
    issues.extend(_boundary_issues(events, start_time=resolved_start))
    issues.extend(
        _session_coverage_issues(
            events,
            sessions_requested=sessions_requested,
            calendar_code=calendar_code,
        )
    )
    ranked = tuple(
        sorted(
            issues,
            key=lambda item: (
                SEVERITY_RANK.get(item.severity, 9),
                item.code,
                item.event_index if item.event_index is not None else -1,
                item.message,
            ),
        )
    )
    counts = Counter(event.kind for event in events)
    try:
        stream_hash = hash_replay_events(events)
    except (DatasetValidationError, SimulationError, ValueError):
        stream_hash = _UNHASHABLE_STREAM
    starts = bool(events) and isinstance(events[0], ReplayStartedEvent)
    ends = bool(events) and isinstance(events[-1], ReplayFinishedEvent)
    boundary_errors = any(
        item.code in _BOUNDARY_ERROR_CODES
        and item.severity == ReplayAuditSeverity.ERROR
        for item in ranked
    )
    return ReplayAuditReport(
        stream_hash=stream_hash,
        event_count=len(events),
        counts_by_kind=dict(counts),
        first_event_time=events[0].event_time if events else None,
        last_event_time=events[-1].event_time if events else None,
        starts_with_replay_started=starts,
        ends_with_replay_finished=ends,
        boundary_ok=starts and ends and not boundary_errors,
        pre_known_event_count=sum(1 for event in events if is_pre_known_event(event)),
        error_count=sum(
            1 for item in ranked if item.severity == ReplayAuditSeverity.ERROR
        ),
        warning_count=sum(
            1 for item in ranked if item.severity == ReplayAuditSeverity.WARNING
        ),
        info_count=sum(
            1 for item in ranked if item.severity == ReplayAuditSeverity.INFO
        ),
        issues=ranked,
    )


def _resolved_start_time(
    events: Sequence[ReplayEvent], explicit: datetime | None
) -> datetime | None:
    for event in events:
        if isinstance(event, ReplayStartedEvent):
            return event.start_time
    return explicit


def _event_issues(
    event: ReplayEvent, *, index: int, as_of: datetime
) -> list[ReplayAuditIssue]:
    found: list[ReplayAuditIssue] = []
    for field_name, instant in _timestamps(event):
        if instant.tzinfo is None:
            found.append(
                ReplayAuditIssue(
                    severity=ReplayAuditSeverity.ERROR,
                    code=ReplayAuditCode.NAIVE_TIMESTAMP,
                    message=f"{field_name} is naive",
                    event_index=index,
                    event_kind=event.kind,
                    metadata={"field": field_name},
                )
            )
        elif (
            as_of.tzinfo is not None and instant > as_of and field_name == "event_time"
        ):
            found.append(
                ReplayAuditIssue(
                    severity=ReplayAuditSeverity.ERROR,
                    code=ReplayAuditCode.LOOKAHEAD,
                    message="event_time must be <= as_of",
                    event_index=index,
                    event_kind=event.kind,
                )
            )
        elif (
            as_of.tzinfo is not None
            and instant > as_of
            and field_name == "available_time"
        ):
            found.append(
                ReplayAuditIssue(
                    severity=ReplayAuditSeverity.ERROR,
                    code=ReplayAuditCode.LOOKAHEAD,
                    message="available_time must be <= as_of",
                    event_index=index,
                    event_kind=event.kind,
                )
            )
    if (
        isinstance(event, MarketBarEvent)
        and not event.known_before_start
        and event.event_time != event.available_time
    ):
        found.append(
            ReplayAuditIssue(
                severity=ReplayAuditSeverity.ERROR,
                code=ReplayAuditCode.BAR_EVENT_TIME_MISMATCH,
                message="bar event_time must equal available_time",
                event_index=index,
                event_kind=MARKET_BAR_KIND,
            )
        )
    if (
        isinstance(event, CorporateActionEvent)
        and not event.known_before_start
        and event.event_time != event.available_time
    ):
        found.append(
            ReplayAuditIssue(
                severity=ReplayAuditSeverity.ERROR,
                code=ReplayAuditCode.CORPORATE_ACTION_EVENT_TIME_MISMATCH,
                message="corporate action event_time must equal available_time",
                event_index=index,
                event_kind=event.kind,
            )
        )
    return found


def _order_issues(events: Sequence[ReplayEvent]) -> list[ReplayAuditIssue]:
    found: list[ReplayAuditIssue] = []
    previous: ReplayEvent | None = None
    previous_index = -1
    for index, event in enumerate(events):
        if previous is not None and replay_event_sort_key(
            event
        ) < replay_event_sort_key(previous):
            found.append(
                ReplayAuditIssue(
                    severity=ReplayAuditSeverity.ERROR,
                    code=ReplayAuditCode.OUT_OF_ORDER,
                    message="event stream is not in canonical order",
                    event_index=index,
                    event_kind=event.kind,
                    metadata={"previous_index": previous_index},
                )
            )
        previous = event
        previous_index = index
    return found


def _boundary_issues(
    events: Sequence[ReplayEvent], *, start_time: datetime | None
) -> list[ReplayAuditIssue]:
    found: list[ReplayAuditIssue] = []
    if not events or not isinstance(events[0], ReplayStartedEvent):
        found.append(
            ReplayAuditIssue(
                severity=ReplayAuditSeverity.ERROR,
                code=ReplayAuditCode.MISSING_STARTED,
                message="stream must start with ReplayStartedEvent",
                event_index=0 if events else None,
                event_kind=events[0].kind if events else None,
            )
        )
    if not events or not isinstance(events[-1], ReplayFinishedEvent):
        found.append(
            ReplayAuditIssue(
                severity=ReplayAuditSeverity.ERROR,
                code=ReplayAuditCode.MISSING_FINISHED,
                message="stream must end with ReplayFinishedEvent",
                event_index=len(events) - 1 if events else None,
                event_kind=events[-1].kind if events else None,
            )
        )
    seen_window = False
    for index, event in enumerate(events):
        if isinstance(event, ReplayStartedEvent | ReplayFinishedEvent):
            continue
        if is_pre_known_event(event):
            if seen_window:
                found.append(
                    ReplayAuditIssue(
                        severity=ReplayAuditSeverity.ERROR,
                        code=ReplayAuditCode.PREKNOWN_MISPLACED,
                        message=(
                            "pre-known fact must appear immediately after "
                            "ReplayStartedEvent"
                        ),
                        event_index=index,
                        event_kind=event.kind,
                    )
                )
        else:
            seen_window = True
        if start_time is None or start_time.tzinfo is None:
            continue
        if event.event_time < start_time:
            found.append(
                ReplayAuditIssue(
                    severity=ReplayAuditSeverity.ERROR,
                    code=ReplayAuditCode.EVENT_BEFORE_START,
                    message="payload event_time must be >= start_time",
                    event_index=index,
                    event_kind=event.kind,
                )
            )
        available = getattr(event, "available_time", None)
        if (
            isinstance(available, datetime)
            and available < start_time
            and not is_pre_known_event(event)
        ):
            found.append(
                ReplayAuditIssue(
                    severity=ReplayAuditSeverity.ERROR,
                    code=ReplayAuditCode.PREKNOWN_UNMARKED,
                    message=(
                        "fact with available_time before start_time must set "
                        "known_before_start"
                    ),
                    event_index=index,
                    event_kind=event.kind,
                )
            )
    return found


def _session_coverage_issues(
    events: Sequence[ReplayEvent],
    *,
    sessions_requested: bool,
    calendar_code: str | None,
) -> list[ReplayAuditIssue]:
    found: list[ReplayAuditIssue] = []
    sessions = [event for event in events if isinstance(event, MarketSessionEvent)]
    if sessions_requested and not calendar_code:
        found.append(
            ReplayAuditIssue(
                severity=ReplayAuditSeverity.INFO,
                code=ReplayAuditCode.SESSIONS_WITHOUT_CALENDAR,
                message="include_sessions has no effect without calendar_code",
            )
        )
    if sessions_requested and calendar_code and not sessions:
        found.append(
            ReplayAuditIssue(
                severity=ReplayAuditSeverity.WARNING,
                code=ReplayAuditCode.MISSING_SESSIONS,
                message=f"calendar {calendar_code!r} has no session events in range",
                metadata={"calendar_code": calendar_code},
            )
        )
    ordered_dates = sorted({item.session_date for item in sessions})
    for left, right in pairwise(ordered_dates):
        gap = (right - left).days
        if gap > 1:
            found.append(
                ReplayAuditIssue(
                    severity=ReplayAuditSeverity.WARNING,
                    code=ReplayAuditCode.SESSION_DATE_GAP,
                    message=(
                        f"calendar sessions skip {gap - 1} day(s) between "
                        f"{left.isoformat()} and {right.isoformat()}"
                    ),
                    metadata={
                        "from": left.isoformat(),
                        "to": right.isoformat(),
                        "gap_days": gap - 1,
                    },
                )
            )
    if sessions_requested and calendar_code and sessions:
        covered = {item.session_date for item in sessions}
        for index, event in enumerate(events):
            if not isinstance(event, MarketBarEvent):
                continue
            observation_day = event.observation_time.date()
            if observation_day not in covered:
                found.append(
                    ReplayAuditIssue(
                        severity=ReplayAuditSeverity.WARNING,
                        code=ReplayAuditCode.BAR_WITHOUT_SESSION,
                        message=(
                            "bar observation_time has no matching session event "
                            f"on {observation_day.isoformat()}"
                        ),
                        event_index=index,
                        event_kind=MARKET_BAR_KIND,
                        metadata={"session_date": observation_day.isoformat()},
                    )
                )
    return found


def _timestamps(event: ReplayEvent) -> list[tuple[str, datetime]]:
    stamps: list[tuple[str, datetime]] = [("event_time", event.event_time)]
    if isinstance(event, MarketBarEvent):
        stamps.extend(
            [
                ("observation_time", event.observation_time),
                ("available_time", event.available_time),
            ]
        )
    elif isinstance(event, CorporateActionEvent):
        stamps.extend(
            [
                ("effective_time", event.effective_time),
                ("available_time", event.available_time),
            ]
        )
    elif isinstance(event, ReplayStartedEvent):
        stamps.extend(
            [
                ("start_time", event.start_time),
                ("end_time", event.end_time),
                ("as_of", event.as_of),
            ]
        )
    elif isinstance(event, ReplayFinishedEvent):
        stamps.extend(
            [
                ("started_at", event.started_at),
                ("finished_at", event.finished_at),
            ]
        )
    return stamps
