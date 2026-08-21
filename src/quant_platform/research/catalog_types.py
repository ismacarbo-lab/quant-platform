"""Research dataset snapshot catalog. Metadata only; no cloud or trading."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from quant_platform.research.errors import DatasetErrorCode, DatasetValidationError
from quant_platform.research.types import build_daily_bars_dataset_request


@dataclass(frozen=True, slots=True)
class DatasetSnapshotCatalogFilters:
    snapshot_id: str | None = None
    content_hash: str | None = None
    manifest_hash: str | None = None
    symbol: str | None = None
    as_of_from: datetime | None = None
    as_of_to: datetime | None = None
    usable_only: bool = False
    git_commit: str | None = None


def build_dataset_snapshot_catalog_filters(
    *,
    snapshot_id: str | None = None,
    content_hash: str | None = None,
    manifest_hash: str | None = None,
    symbol: str | None = None,
    as_of_from: datetime | None = None,
    as_of_to: datetime | None = None,
    usable_only: bool = False,
    git_commit: str | None = None,
) -> DatasetSnapshotCatalogFilters:
    """Validate list filters. Timestamps must be timezone-aware when present."""
    if as_of_from is not None or as_of_to is not None:
        start = as_of_from if as_of_from is not None else as_of_to
        end = as_of_to if as_of_to is not None else as_of_from
        build_daily_bars_dataset_request(
            as_of=end,
            start_time=start,
            end_time=end,
            allow_unfiltered=True,
        )
    if as_of_from is not None and as_of_to is not None and as_of_from > as_of_to:
        raise DatasetValidationError(
            "as_of_from must be <= as_of_to",
            code=DatasetErrorCode.INVALID_RANGE,
        )
    cleaned_symbol = _optional_token(symbol, field="symbol")
    return DatasetSnapshotCatalogFilters(
        snapshot_id=_optional_token(snapshot_id, field="snapshot_id"),
        content_hash=_optional_token(content_hash, field="content_hash"),
        manifest_hash=_optional_token(manifest_hash, field="manifest_hash"),
        symbol=cleaned_symbol,
        as_of_from=as_of_from,
        as_of_to=as_of_to,
        usable_only=usable_only,
        git_commit=_optional_token(git_commit, field="git_commit"),
    )


def _optional_token(value: str | None, *, field: str) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        raise DatasetValidationError(
            f"{field} must not be empty",
            code=DatasetErrorCode.EMPTY_FILTER,
        )
    return stripped


@dataclass(frozen=True, slots=True)
class DatasetSnapshotCatalogEntry:
    snapshot_id: str
    content_hash: str
    quality_hash: str
    manifest_hash: str
    package_version: str
    git_commit: str | None
    created_at: datetime
    as_of: datetime
    start_time: datetime
    end_time: datetime
    row_count: int
    instrument_count: int
    warning_count: int
    error_count: int
    is_reproducible: bool
    is_usable: bool
    dataset_request: dict[str, object]
    quality_summary: dict[str, object]
    artifacts: tuple[dict[str, object], ...]
    notes: str | None
    registered_at: datetime

    def as_mapping(self) -> dict[str, object]:
        return {
            "snapshot_id": self.snapshot_id,
            "content_hash": self.content_hash,
            "quality_hash": self.quality_hash,
            "manifest_hash": self.manifest_hash,
            "package_version": self.package_version,
            "git_commit": self.git_commit,
            "created_at": self.created_at.isoformat(),
            "as_of": self.as_of.isoformat(),
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "row_count": self.row_count,
            "instrument_count": self.instrument_count,
            "warning_count": self.warning_count,
            "error_count": self.error_count,
            "is_reproducible": self.is_reproducible,
            "is_usable": self.is_usable,
            "dataset_request": self.dataset_request,
            "quality_summary": self.quality_summary,
            "artifacts": list(self.artifacts),
            "notes": self.notes,
            "registered_at": self.registered_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class DatasetSnapshotComparison:
    snapshot_a_id: str
    snapshot_b_id: str
    same_content_hash: bool
    same_quality_hash: bool
    same_manifest_hash: bool
    same_as_of: bool
    same_git_commit: bool
    same_package_version: bool
    same_start_time: bool
    same_end_time: bool
    same_artifact_paths: bool
    row_count_delta: int
    instrument_count_delta: int
    error_count_delta: int
    warning_count_delta: int
    differences: tuple[str, ...]

    def as_mapping(self) -> dict[str, object]:
        return {
            "snapshot_a_id": self.snapshot_a_id,
            "snapshot_b_id": self.snapshot_b_id,
            "same_content_hash": self.same_content_hash,
            "same_quality_hash": self.same_quality_hash,
            "same_manifest_hash": self.same_manifest_hash,
            "same_as_of": self.same_as_of,
            "same_git_commit": self.same_git_commit,
            "same_package_version": self.same_package_version,
            "same_start_time": self.same_start_time,
            "same_end_time": self.same_end_time,
            "same_artifact_paths": self.same_artifact_paths,
            "row_count_delta": self.row_count_delta,
            "instrument_count_delta": self.instrument_count_delta,
            "error_count_delta": self.error_count_delta,
            "warning_count_delta": self.warning_count_delta,
            "differences": list(self.differences),
        }


@dataclass(frozen=True, slots=True)
class DatasetSnapshotRegistration:
    entry: DatasetSnapshotCatalogEntry
    action: str


def artifacts_have_absolute_paths(artifacts: Sequence[Mapping[str, object]]) -> bool:
    return any(_artifact_path_is_absolute(item) for item in artifacts)


def _artifact_path_is_absolute(item: Mapping[str, object]) -> bool:
    path = item.get("path")
    if not isinstance(path, str) or not path.strip():
        return True
    candidate = Path(path)
    return candidate.is_absolute() or ".." in candidate.parts
