"""Deterministic daily-bar replay. No strategies, signals, or trading."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from quant_platform.data.validation import DataValidationError, ensure_utc
from quant_platform.research.catalog_integrity import (
    load_snapshot_daily_bar_rows,
    verify_snapshot_artifacts,
)
from quant_platform.research.datasets import get_daily_bars_dataset
from quant_platform.research.errors import DatasetValidationError
from quant_platform.research.snapshot_types import (
    DAILY_BARS_ARTIFACT_NAME,
    MANIFEST_ARTIFACT_NAME,
)
from quant_platform.research.snapshots import hash_daily_bars_dataset
from quant_platform.research.types import (
    DailyBarDatasetRow,
    DailyBarsDataset,
    DailyBarsDatasetRequest,
    build_daily_bars_dataset_request,
)
from quant_platform.simulation.clock import SimulationClock
from quant_platform.simulation.errors import SimulationError, SimulationErrorCode
from quant_platform.simulation.events import (
    MarketBarEvent,
    ReplayEvent,
    ReplayFinishedEvent,
    ReplayStartedEvent,
    market_bar_event_from_row,
)
from quant_platform.simulation.summary import (
    SOURCE_DATABASE,
    SOURCE_SNAPSHOT,
    ReplaySummary,
)


@dataclass(frozen=True, slots=True)
class DailyBarReplay:
    """Immutable replay: started, bars in available_time order, finished."""

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


def replay_daily_bars_dataset(
    dataset: DailyBarsDataset,
    *,
    replay_id: UUID | None = None,
    source_type: str = SOURCE_DATABASE,
    content_hash: str | None = None,
    warnings: Sequence[str] = (),
) -> DailyBarReplay:
    """Emit a deterministic event stream from an in-memory PIT dataset.

    ``event_time`` for each bar is ``available_time`` so a consumer never sees
    a close before it was knowable. Dataset sort (observation time) is not
    the replay order.
    """
    request = dataset.request
    as_of = _utc(request.as_of, field="as_of")
    start_time = _utc(request.start_time, field="start_time")
    end_time = _utc(request.end_time, field="end_time")
    bars = tuple(_bar_event(row, as_of=as_of) for row in dataset.rows)
    ordered = tuple(sorted(bars, key=_bar_event_sort_key))
    instrument_ids = {event.instrument_id for event in ordered}
    instrument_count = len(instrument_ids)
    started = ReplayStartedEvent(
        event_time=start_time,
        start_time=start_time,
        end_time=end_time,
        as_of=as_of,
        instrument_count=instrument_count,
    )
    first_bar_time = ordered[0].event_time if ordered else None
    last_bar_time = ordered[-1].event_time if ordered else None
    finished_at = last_bar_time if last_bar_time is not None else end_time
    if finished_at < start_time:
        finished_at = start_time
    event_count = len(ordered) + 2
    finished = ReplayFinishedEvent(
        event_time=finished_at,
        started_at=start_time,
        finished_at=finished_at,
        event_count=event_count,
        bar_count=len(ordered),
        instrument_count=instrument_count,
    )
    events: tuple[ReplayEvent, ...] = (started, *ordered, finished)
    clock = SimulationClock()
    for event in events:
        clock.advance_to(event.event_time)
    digest = (
        content_hash if content_hash is not None else hash_daily_bars_dataset(dataset)
    )
    summary = ReplaySummary(
        replay_id=replay_id or uuid4(),
        started_at=start_time,
        finished_at=finished_at,
        start_time=start_time,
        end_time=end_time,
        as_of=as_of,
        event_count=event_count,
        bar_count=len(ordered),
        instrument_count=instrument_count,
        first_event_time=first_bar_time,
        last_event_time=last_bar_time,
        content_hash=digest,
        source_type=source_type,
        warnings=tuple(warnings),
    )
    return DailyBarReplay(events=events, summary=summary)


def create_daily_bar_replay(
    session: Session,
    request: DailyBarsDatasetRequest,
    *,
    replay_id: UUID | None = None,
) -> DailyBarReplay:
    """Load a PIT dataset from PostgreSQL and replay it."""
    dataset = get_daily_bars_dataset(session, request)
    return replay_daily_bars_dataset(
        dataset, replay_id=replay_id, source_type=SOURCE_DATABASE
    )


def replay_daily_bars_snapshot(
    snapshot_dir: Path | str,
    *,
    replay_id: UUID | None = None,
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
    return replay_daily_bars_dataset(
        dataset,
        replay_id=replay_id,
        source_type=SOURCE_SNAPSHOT,
        content_hash=content_hash,
    )


def _bar_event(row: DailyBarDatasetRow, *, as_of: datetime) -> MarketBarEvent:
    event = market_bar_event_from_row(row)
    if event.event_time != event.available_time:
        raise SimulationError(
            "bar event_time must equal available_time",
            code=SimulationErrorCode.INVALID_EVENT_TIME,
        )
    if event.available_time > as_of:
        raise SimulationError(
            "available_time must be <= as_of",
            code=SimulationErrorCode.LOOKAHEAD,
        )
    return event


def _bar_event_sort_key(event: MarketBarEvent) -> tuple[object, ...]:
    return (
        event.event_time,
        event.symbol,
        event.exchange_code or "",
        str(event.instrument_id),
        event.observation_time,
        event.source_name,
    )


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
