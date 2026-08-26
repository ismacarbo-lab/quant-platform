"""Deterministic hashes for replay event streams. No wall-clock, no replay_id."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import date, time
from uuid import UUID

from quant_platform.research.snapshots import (
    canonical_datetime,
    canonical_decimal,
    dataset_request_mapping,
    is_sha256_digest,
    sha256_canonical,
)
from quant_platform.research.types import DailyBarsDatasetRequest
from quant_platform.simulation.errors import SimulationError, SimulationErrorCode
from quant_platform.simulation.events import (
    CorporateActionEvent,
    MarketBarEvent,
    MarketSessionEvent,
    ReplayEvent,
    ReplayFinishedEvent,
    ReplayStartedEvent,
)

STREAM_HASH_KIND = "replay_event_stream"
REQUEST_HASH_KIND = "daily_bars_dataset_request"
STREAM_HASH_FORMAT_VERSION = 2
REQUEST_HASH_FORMAT_VERSION = 1
HASH_FORMAT_VERSION = STREAM_HASH_FORMAT_VERSION


def hash_replay_events(events: Sequence[ReplayEvent]) -> str:
    """SHA-256 of the canonical event stream. Caller order is hashed as-is."""
    payload = {
        "kind": STREAM_HASH_KIND,
        "version": STREAM_HASH_FORMAT_VERSION,
        "events": [_canonical_event(event) for event in events],
    }
    return sha256_canonical(payload)


def hash_replay_request(request: DailyBarsDatasetRequest) -> str:
    """SHA-256 of the dataset request. Used with ``derive_replay_id``."""
    payload = {
        "kind": REQUEST_HASH_KIND,
        "version": REQUEST_HASH_FORMAT_VERSION,
        "request": dataset_request_mapping(request),
    }
    return sha256_canonical(payload)


def derive_replay_id(stream_hash: str, request_hash: str | None = None) -> UUID:
    """Stable UUID from stream hash (and optional request hash).

    Default replay still uses UUID4. Pass ``deterministic_id=True`` or call
    this helper when a stable id is required.
    """
    if not is_sha256_digest(stream_hash):
        raise SimulationError(
            "stream_hash must be sha256:<64 hex>",
            code=SimulationErrorCode.INVALID_EVENT_TIME,
        )
    material = stream_hash if request_hash is None else f"{stream_hash}\n{request_hash}"
    digest = hashlib.sha256(material.encode("utf-8")).digest()
    return UUID(bytes=digest[:16])


def _canonical_event(event: ReplayEvent) -> dict[str, object]:
    if isinstance(event, ReplayStartedEvent):
        return {
            "kind": event.kind,
            "event_time": canonical_datetime(event.event_time),
            "start_time": canonical_datetime(event.start_time),
            "end_time": canonical_datetime(event.end_time),
            "as_of": canonical_datetime(event.as_of),
            "instrument_count": event.instrument_count,
        }
    if isinstance(event, MarketSessionEvent):
        return {
            "kind": event.kind,
            "event_time": canonical_datetime(event.event_time),
            "session_date": _canonical_date(event.session_date),
            "calendar_code": event.calendar_code,
            "exchange_code": event.exchange_code or "",
            "session_kind": event.session_kind,
            "is_open": event.is_open,
            "open_time": _canonical_clock(event.open_time),
            "close_time": _canonical_clock(event.close_time),
            "note": event.note or "",
            "known_before_start": event.known_before_start,
        }
    if isinstance(event, CorporateActionEvent):
        return {
            "kind": event.kind,
            "event_time": canonical_datetime(event.event_time),
            "effective_time": canonical_datetime(event.effective_time),
            "available_time": canonical_datetime(event.available_time),
            "instrument_id": str(event.instrument_id),
            "symbol": event.symbol,
            "exchange_code": event.exchange_code or "",
            "action_type": event.action_type,
            "value": event.value or "",
            "currency": event.currency or "",
            "description": event.description or "",
            "known_before_start": event.known_before_start,
        }
    if isinstance(event, MarketBarEvent):
        return {
            "kind": event.kind,
            "event_time": canonical_datetime(event.event_time),
            "observation_time": canonical_datetime(event.observation_time),
            "available_time": canonical_datetime(event.available_time),
            "instrument_id": str(event.instrument_id),
            "symbol": event.symbol,
            "exchange_code": event.exchange_code or "",
            "asset_class": event.asset_class,
            "currency": event.currency or "",
            "open": canonical_decimal(event.open),
            "high": canonical_decimal(event.high),
            "low": canonical_decimal(event.low),
            "close": canonical_decimal(event.close),
            "volume": canonical_decimal(event.volume),
            "source_name": event.source_name,
            "is_correction": event.is_correction,
            "correction_reason": event.correction_reason or "",
            "known_before_start": event.known_before_start,
        }
    if isinstance(event, ReplayFinishedEvent):
        return {
            "kind": event.kind,
            "event_time": canonical_datetime(event.event_time),
            "started_at": canonical_datetime(event.started_at),
            "finished_at": canonical_datetime(event.finished_at),
            "event_count": event.event_count,
            "bar_count": event.bar_count,
            "instrument_count": event.instrument_count,
        }
    raise SimulationError(
        f"unsupported replay event type {type(event)!r}",
        code=SimulationErrorCode.INVALID_EVENT_TIME,
    )


def _canonical_date(value: date) -> str:
    return value.isoformat()


def _canonical_clock(value: time | None) -> str:
    if value is None:
        return ""
    return value.isoformat()
