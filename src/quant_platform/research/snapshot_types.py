"""Typed dataset snapshot shapes. Dataclasses, not Pydantic."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import UUID

from quant_platform.research.errors import DatasetErrorCode, DatasetValidationError
from quant_platform.research.quality_types import (
    DatasetQualityRequest,
    build_dataset_quality_request,
)
from quant_platform.research.types import DailyBarsDatasetRequest

SNAPSHOT_KIND = "daily_bars_dataset_snapshot"
SNAPSHOT_FORMAT_VERSION = 1

DAILY_BARS_ARTIFACT_NAME = "daily_bars.csv"
QUALITY_ARTIFACT_NAME = "quality.json"
MANIFEST_ARTIFACT_NAME = "manifest.json"


def _optional_notes(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


@dataclass(frozen=True, slots=True)
class DatasetSnapshotRequest:
    """Local snapshot of a PIT dataset plus its quality report."""

    dataset: DailyBarsDatasetRequest
    strict_calendar: bool = False
    long_gap_open_sessions: int = 5
    notes: str | None = None

    def quality_request(self) -> DatasetQualityRequest:
        return DatasetQualityRequest(
            dataset=self.dataset,
            strict_calendar=self.strict_calendar,
            long_gap_open_sessions=self.long_gap_open_sessions,
        )


def build_dataset_snapshot_request(
    *,
    as_of: datetime | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    symbols: Sequence[str] | None = None,
    instrument_ids: Sequence[UUID] | None = None,
    exchange_codes: Sequence[str] | None = None,
    asset_classes: Sequence[str] | None = None,
    currency: str | None = None,
    calendar_code: str | None = None,
    require_open_session: bool = False,
    allow_unfiltered: bool = False,
    strict_calendar: bool = False,
    long_gap_open_sessions: int = 5,
    notes: str | None = None,
) -> DatasetSnapshotRequest:
    quality = build_dataset_quality_request(
        as_of=as_of,
        start_time=start_time,
        end_time=end_time,
        symbols=symbols,
        instrument_ids=instrument_ids,
        exchange_codes=exchange_codes,
        asset_classes=asset_classes,
        currency=currency,
        calendar_code=calendar_code,
        require_open_session=require_open_session,
        allow_unfiltered=allow_unfiltered,
        strict_calendar=strict_calendar,
        long_gap_open_sessions=long_gap_open_sessions,
    )
    return DatasetSnapshotRequest(
        dataset=quality.dataset,
        strict_calendar=quality.strict_calendar,
        long_gap_open_sessions=quality.long_gap_open_sessions,
        notes=_optional_notes(notes),
    )


@dataclass(frozen=True, slots=True)
class SnapshotArtifact:
    name: str
    path: str
    kind: str

    def as_mapping(self) -> dict[str, object]:
        if Path(self.path).is_absolute():
            raise DatasetValidationError(
                "snapshot artifact paths must be relative",
                code=DatasetErrorCode.INVALID_RANGE,
            )
        return {"name": self.name, "path": self.path, "kind": self.kind}


@dataclass(frozen=True, slots=True)
class DatasetSnapshotManifest:
    snapshot_id: UUID
    created_at: datetime
    package_version: str
    git_commit: str | None
    dataset_request: dict[str, object]
    quality_request: dict[str, object]
    row_count: int
    instrument_count: int
    error_count: int
    warning_count: int
    info_count: int
    content_hash: str
    quality_hash: str
    manifest_hash: str
    artifacts: tuple[SnapshotArtifact, ...]
    notes: str | None

    def as_mapping(self, *, include_manifest_hash: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "kind": SNAPSHOT_KIND,
            "format_version": SNAPSHOT_FORMAT_VERSION,
            "snapshot_id": str(self.snapshot_id),
            "created_at": self.created_at.isoformat(),
            "package_version": self.package_version,
            "git_commit": self.git_commit,
            "as_of": self.dataset_request["as_of"],
            "start_time": self.dataset_request["start_time"],
            "end_time": self.dataset_request["end_time"],
            "dataset_request": self.dataset_request,
            "quality_request": self.quality_request,
            "row_count": self.row_count,
            "instrument_count": self.instrument_count,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "info_count": self.info_count,
            "content_hash": self.content_hash,
            "quality_hash": self.quality_hash,
            "artifacts": [item.as_mapping() for item in self.artifacts],
            "notes": self.notes,
        }
        if include_manifest_hash:
            payload["manifest_hash"] = self.manifest_hash
        return payload


@dataclass(frozen=True, slots=True)
class DatasetSnapshotResult:
    manifest: DatasetSnapshotManifest
    output_dir: Path
    daily_bars_path: Path
    quality_path: Path
    manifest_path: Path
