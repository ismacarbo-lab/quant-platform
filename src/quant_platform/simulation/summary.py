"""Immutable replay summary. Not persisted; not a backtest report."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


SOURCE_DATABASE = "database"
SOURCE_SNAPSHOT = "snapshot"


@dataclass(frozen=True, slots=True)
class ReplaySummary:
    replay_id: UUID
    started_at: datetime
    finished_at: datetime
    start_time: datetime
    end_time: datetime
    as_of: datetime
    event_count: int
    bar_count: int
    instrument_count: int
    first_event_time: datetime | None
    last_event_time: datetime | None
    content_hash: str | None
    source_type: str
    warnings: tuple[str, ...]

    def as_mapping(self) -> dict[str, object]:
        return {
            "replay_id": str(self.replay_id),
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "as_of": self.as_of.isoformat(),
            "event_count": self.event_count,
            "bar_count": self.bar_count,
            "instrument_count": self.instrument_count,
            "first_event_time": _iso(self.first_event_time),
            "last_event_time": _iso(self.last_event_time),
            "content_hash": self.content_hash,
            "source_type": self.source_type,
            "warnings": list(self.warnings),
        }
