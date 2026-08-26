"""Load deterministic replay event fixtures. Test helpers, not persisted runs."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import UUID

from quant_platform.simulation.errors import SimulationError, SimulationErrorCode
from quant_platform.simulation.events import (
    CORPORATE_ACTION_KIND,
    MARKET_BAR_KIND,
    MARKET_SESSION_KIND,
    REPLAY_FINISHED_KIND,
    REPLAY_STARTED_KIND,
    CorporateActionEvent,
    MarketBarEvent,
    MarketSessionEvent,
    ReplayEvent,
    ReplayFinishedEvent,
    ReplayStartedEvent,
)

_FORBIDDEN_KIND_FRAGMENTS = (
    "order",
    "trade",
    "fill",
    "signal",
    "position",
    "portfolio",
)


@dataclass(frozen=True, slots=True)
class ReplayEventFixture:
    description: str
    events: tuple[ReplayEvent, ...]

    def as_mapping(self) -> dict[str, object]:
        return {
            "description": self.description,
            "events": [event.as_mapping() for event in self.events],
        }


def replay_event_fixtures_dir() -> Path:
    """Resolve ``tests/fixtures/replay_events`` from the repository root."""
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "tests" / "fixtures" / "replay_events"
        if candidate.is_dir():
            return candidate
    raise SimulationError(
        "replay event fixtures directory is missing",
        code=SimulationErrorCode.INVALID_EVENT_TIME,
    )


def load_replay_events_json(path: Path | str) -> ReplayEventFixture:
    """Parse a small JSON fixture into typed replay events."""
    root = Path(path)
    try:
        text = root.read_text(encoding="utf-8")
    except OSError as exc:
        raise SimulationError(
            "replay event fixture cannot be read",
            code=SimulationErrorCode.INVALID_EVENT_TIME,
        ) from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SimulationError(
            "replay event fixture is not valid JSON",
            code=SimulationErrorCode.INVALID_EVENT_TIME,
        ) from exc
    if not isinstance(payload, dict):
        raise SimulationError(
            "replay event fixture must be an object",
            code=SimulationErrorCode.INVALID_EVENT_TIME,
        )
    description = payload.get("description")
    if not isinstance(description, str) or not description.strip():
        raise SimulationError(
            "replay event fixture description is required",
            code=SimulationErrorCode.INVALID_EVENT_TIME,
        )
    raw_events = payload.get("events")
    if not isinstance(raw_events, list) or not raw_events:
        raise SimulationError(
            "replay event fixture events must be a non-empty list",
            code=SimulationErrorCode.INVALID_EVENT_TIME,
        )
    events: list[ReplayEvent] = []
    for item in raw_events:
        if not isinstance(item, dict):
            raise SimulationError(
                "replay event fixture event must be an object",
                code=SimulationErrorCode.INVALID_EVENT_TIME,
            )
        events.append(_event_from_mapping(item))
    return ReplayEventFixture(description=description.strip(), events=tuple(events))


def _event_from_mapping(payload: Mapping[str, object]) -> ReplayEvent:
    kind = _require_str(payload, "kind")
    lowered = kind.lower()
    if any(fragment in lowered for fragment in _FORBIDDEN_KIND_FRAGMENTS):
        raise SimulationError(
            f"replay event fixture contains a trading kind {kind!r}",
            code=SimulationErrorCode.INVALID_EVENT_TIME,
        )
    if kind == REPLAY_STARTED_KIND:
        return ReplayStartedEvent(
            event_time=_require_datetime(payload, "event_time"),
            start_time=_require_datetime(payload, "start_time"),
            end_time=_require_datetime(payload, "end_time"),
            as_of=_require_datetime(payload, "as_of"),
            instrument_count=_require_int(payload, "instrument_count"),
        )
    if kind == MARKET_SESSION_KIND:
        return MarketSessionEvent(
            event_time=_require_datetime(payload, "event_time"),
            session_date=_require_date(payload, "session_date"),
            calendar_code=_require_str(payload, "calendar_code"),
            exchange_code=_optional_str(payload, "exchange_code"),
            session_kind=_require_str(payload, "session_kind"),
            is_open=_require_bool(payload, "is_open"),
            open_time=_optional_time(payload, "open_time"),
            close_time=_optional_time(payload, "close_time"),
            note=_optional_str(payload, "note"),
            known_before_start=_optional_bool(payload, "known_before_start"),
        )
    if kind == CORPORATE_ACTION_KIND:
        return CorporateActionEvent(
            event_time=_require_datetime(payload, "event_time"),
            effective_time=_require_datetime(payload, "effective_time"),
            available_time=_require_datetime(payload, "available_time"),
            instrument_id=_require_uuid(payload, "instrument_id"),
            symbol=_require_str(payload, "symbol"),
            exchange_code=_optional_str(payload, "exchange_code"),
            action_type=_require_str(payload, "action_type"),
            value=_optional_str(payload, "value"),
            currency=_optional_str(payload, "currency"),
            description=_optional_str(payload, "description"),
            known_before_start=_optional_bool(payload, "known_before_start"),
        )
    if kind == MARKET_BAR_KIND:
        return MarketBarEvent(
            event_time=_require_datetime(payload, "event_time"),
            observation_time=_require_datetime(payload, "observation_time"),
            available_time=_require_datetime(payload, "available_time"),
            instrument_id=_require_uuid(payload, "instrument_id"),
            symbol=_require_str(payload, "symbol"),
            exchange_code=_optional_str(payload, "exchange_code"),
            asset_class=_require_str(payload, "asset_class"),
            currency=_optional_str(payload, "currency"),
            open=_require_decimal(payload, "open"),
            high=_require_decimal(payload, "high"),
            low=_require_decimal(payload, "low"),
            close=_require_decimal(payload, "close"),
            volume=_optional_decimal(payload, "volume"),
            source_name=_require_str(payload, "source_name"),
            is_correction=_require_bool(payload, "is_correction"),
            correction_reason=_optional_str(payload, "correction_reason"),
            known_before_start=_optional_bool(payload, "known_before_start"),
        )
    if kind == REPLAY_FINISHED_KIND:
        return ReplayFinishedEvent(
            event_time=_require_datetime(payload, "event_time"),
            started_at=_require_datetime(payload, "started_at"),
            finished_at=_require_datetime(payload, "finished_at"),
            event_count=_require_int(payload, "event_count"),
            bar_count=_require_int(payload, "bar_count"),
            instrument_count=_require_int(payload, "instrument_count"),
        )
    raise SimulationError(
        f"unsupported replay event kind {kind!r}",
        code=SimulationErrorCode.INVALID_EVENT_TIME,
    )


def _require_str(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise SimulationError(
            f"fixture field {key!r} must be a non-empty string",
            code=SimulationErrorCode.INVALID_EVENT_TIME,
        )
    return value


def _optional_str(payload: Mapping[str, object], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise SimulationError(
            f"fixture field {key!r} must be a string or null",
            code=SimulationErrorCode.INVALID_EVENT_TIME,
        )
    return value or None


def _require_bool(payload: Mapping[str, object], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise SimulationError(
            f"fixture field {key!r} must be a boolean",
            code=SimulationErrorCode.INVALID_EVENT_TIME,
        )
    return value


def _optional_bool(payload: Mapping[str, object], key: str) -> bool:
    value = payload.get(key)
    if value is None:
        return False
    if not isinstance(value, bool):
        raise SimulationError(
            f"fixture field {key!r} must be a boolean",
            code=SimulationErrorCode.INVALID_EVENT_TIME,
        )
    return value


def _require_int(payload: Mapping[str, object], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise SimulationError(
            f"fixture field {key!r} must be an integer",
            code=SimulationErrorCode.INVALID_EVENT_TIME,
        )
    return value


def _require_uuid(payload: Mapping[str, object], key: str) -> UUID:
    try:
        return UUID(_require_str(payload, key))
    except ValueError as exc:
        raise SimulationError(
            f"fixture field {key!r} must be a UUID",
            code=SimulationErrorCode.INVALID_EVENT_TIME,
        ) from exc


def _require_datetime(payload: Mapping[str, object], key: str) -> datetime:
    raw = _require_str(payload, key)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SimulationError(
            f"fixture field {key!r} must be an ISO-8601 datetime",
            code=SimulationErrorCode.INVALID_EVENT_TIME,
        ) from exc
    if parsed.tzinfo is None:
        raise SimulationError(
            f"fixture field {key!r} must be timezone-aware UTC",
            code=SimulationErrorCode.NAIVE_TIMESTAMP,
        )
    return parsed


def _require_date(payload: Mapping[str, object], key: str) -> date:
    raw = _require_str(payload, key)
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise SimulationError(
            f"fixture field {key!r} must be an ISO-8601 date",
            code=SimulationErrorCode.INVALID_EVENT_TIME,
        ) from exc


def _optional_time(payload: Mapping[str, object], key: str) -> time | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise SimulationError(
            f"fixture field {key!r} must be a time string or null",
            code=SimulationErrorCode.INVALID_EVENT_TIME,
        )
    try:
        return time.fromisoformat(value)
    except ValueError as exc:
        raise SimulationError(
            f"fixture field {key!r} must be an ISO-8601 time",
            code=SimulationErrorCode.INVALID_EVENT_TIME,
        ) from exc


def _require_decimal(payload: Mapping[str, object], key: str) -> Decimal:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, str | int | float | Decimal):
        raise SimulationError(
            f"fixture field {key!r} must be a decimal",
            code=SimulationErrorCode.INVALID_EVENT_TIME,
        )
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise SimulationError(
            f"fixture field {key!r} must be a decimal",
            code=SimulationErrorCode.INVALID_EVENT_TIME,
        ) from exc


def _optional_decimal(payload: Mapping[str, object], key: str) -> Decimal | None:
    value = payload.get(key)
    if value is None or value == "":
        return None
    return _require_decimal(payload, key)
