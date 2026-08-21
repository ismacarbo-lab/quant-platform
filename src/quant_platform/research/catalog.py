"""PostgreSQL catalog of local dataset snapshots. Metadata only."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from quant_platform.data.models import DatasetSnapshotRecord
from quant_platform.research.catalog_types import (
    DatasetSnapshotCatalogEntry,
    DatasetSnapshotCatalogFilters,
    DatasetSnapshotComparison,
    DatasetSnapshotRegistration,
    artifacts_have_absolute_paths,
    build_dataset_snapshot_catalog_filters,
)
from quant_platform.research.errors import DatasetErrorCode, DatasetValidationError
from quant_platform.research.snapshot_types import DatasetSnapshotManifest
from quant_platform.research.snapshots import (
    is_sha256_digest,
    manifest_contains_secrets,
)


def validate_catalog_manifest(manifest: DatasetSnapshotManifest) -> None:
    """Reject manifests that cannot be stored as catalog metadata."""
    if manifest.row_count < 0 or manifest.instrument_count < 0:
        raise DatasetValidationError(
            "row_count and instrument_count must be >= 0",
            code=DatasetErrorCode.CATALOG_INVALID,
        )
    if manifest.error_count < 0 or manifest.warning_count < 0:
        raise DatasetValidationError(
            "error_count and warning_count must be >= 0",
            code=DatasetErrorCode.CATALOG_INVALID,
        )
    for label, value in (
        ("content_hash", manifest.content_hash),
        ("quality_hash", manifest.quality_hash),
        ("manifest_hash", manifest.manifest_hash),
    ):
        if not is_sha256_digest(value):
            raise DatasetValidationError(
                f"{label} must be a sha256:<hex> digest",
                code=DatasetErrorCode.CATALOG_INVALID,
            )
    if not manifest.artifacts:
        raise DatasetValidationError(
            "snapshot artifacts must not be empty",
            code=DatasetErrorCode.CATALOG_INVALID,
        )
    mappings = tuple(item.as_mapping() for item in manifest.artifacts)
    if artifacts_have_absolute_paths(mappings):
        raise DatasetValidationError(
            "snapshot artifact paths must be relative",
            code=DatasetErrorCode.CATALOG_INVALID,
        )
    blob = {
        "artifacts": [dict(item) for item in mappings],
        "dataset_request": manifest.dataset_request,
        "notes": manifest.notes or "",
    }
    if manifest_contains_secrets(blob):
        raise DatasetValidationError(
            "catalog metadata must not contain secrets",
            code=DatasetErrorCode.CATALOG_INVALID,
        )
    _parse_request_time(manifest.dataset_request, "as_of")
    _parse_request_time(manifest.dataset_request, "start_time")
    _parse_request_time(manifest.dataset_request, "end_time")
    if manifest.created_at.tzinfo is None:
        raise DatasetValidationError(
            "created_at must be timezone-aware UTC",
            code=DatasetErrorCode.NAIVE_TIMESTAMP,
        )


def snapshot_is_reproducible(manifest: DatasetSnapshotManifest) -> bool:
    """True when hashes, relative artifacts, and counts are catalog-valid."""
    try:
        validate_catalog_manifest(manifest)
    except DatasetValidationError:
        return False
    return True


def snapshot_is_usable(manifest: DatasetSnapshotManifest) -> bool:
    """True when the snapshot is reproducible and quality has zero errors."""
    return snapshot_is_reproducible(manifest) and manifest.error_count == 0


def register_dataset_snapshot(
    session: Session,
    manifest: DatasetSnapshotManifest,
    base_path: Path | str | None = None,
) -> DatasetSnapshotRegistration:
    """Upsert catalog metadata by ``snapshot_id``. Unique on ``manifest_hash``.

    ``base_path`` is not stored (absolute directories would leak local paths).
    """
    del base_path
    validate_catalog_manifest(manifest)
    snapshot_id = str(manifest.snapshot_id)
    other = get_dataset_snapshot_by_manifest_hash(session, manifest.manifest_hash)
    if other is not None and other.snapshot_id != snapshot_id:
        raise DatasetValidationError(
            "manifest_hash already registered under a different snapshot_id",
            code=DatasetErrorCode.CATALOG_CONFLICT,
        )
    existing = session.scalars(
        select(DatasetSnapshotRecord).where(
            DatasetSnapshotRecord.snapshot_id == snapshot_id
        )
    ).first()
    payload = _record_payload(manifest)
    if existing is None:
        row = DatasetSnapshotRecord(**cast(dict[str, Any], payload))
        session.add(row)
        session.flush()
        return DatasetSnapshotRegistration(
            entry=_entry_from_record(row), action="insert"
        )
    _apply_payload(existing, payload)
    session.flush()
    return DatasetSnapshotRegistration(
        entry=_entry_from_record(existing), action="update"
    )


def get_dataset_snapshot_by_id(
    session: Session, snapshot_id: str
) -> DatasetSnapshotCatalogEntry | None:
    stmt = select(DatasetSnapshotRecord).where(
        DatasetSnapshotRecord.snapshot_id == snapshot_id.strip()
    )
    row = session.scalars(stmt).first()
    if row is None:
        return None
    return _entry_from_record(row)


def get_dataset_snapshot_by_manifest_hash(
    session: Session, manifest_hash: str
) -> DatasetSnapshotCatalogEntry | None:
    stmt = select(DatasetSnapshotRecord).where(
        DatasetSnapshotRecord.manifest_hash == manifest_hash.strip()
    )
    row = session.scalars(stmt).first()
    if row is None:
        return None
    return _entry_from_record(row)


def list_dataset_snapshots(
    session: Session,
    filters: DatasetSnapshotCatalogFilters | None = None,
) -> tuple[DatasetSnapshotCatalogEntry, ...]:
    query = filters or build_dataset_snapshot_catalog_filters()
    stmt = select(DatasetSnapshotRecord)
    if query.snapshot_id is not None:
        stmt = stmt.where(DatasetSnapshotRecord.snapshot_id == query.snapshot_id)
    if query.content_hash is not None:
        stmt = stmt.where(DatasetSnapshotRecord.content_hash == query.content_hash)
    if query.manifest_hash is not None:
        stmt = stmt.where(DatasetSnapshotRecord.manifest_hash == query.manifest_hash)
    if query.git_commit is not None:
        stmt = stmt.where(DatasetSnapshotRecord.git_commit == query.git_commit)
    if query.usable_only:
        stmt = stmt.where(DatasetSnapshotRecord.is_usable.is_(True))
    if query.as_of_from is not None:
        stmt = stmt.where(DatasetSnapshotRecord.as_of >= query.as_of_from)
    if query.as_of_to is not None:
        stmt = stmt.where(DatasetSnapshotRecord.as_of <= query.as_of_to)
    if query.symbol is not None:
        stmt = stmt.where(
            DatasetSnapshotRecord.dataset_request.contains({"symbols": [query.symbol]})
        )
    stmt = stmt.order_by(
        DatasetSnapshotRecord.created_at.desc(),
        DatasetSnapshotRecord.snapshot_id.asc(),
    )
    return tuple(_entry_from_record(row) for row in session.scalars(stmt))


def compare_dataset_snapshots(
    snapshot_a: DatasetSnapshotCatalogEntry | DatasetSnapshotManifest,
    snapshot_b: DatasetSnapshotCatalogEntry | DatasetSnapshotManifest,
) -> DatasetSnapshotComparison:
    left = _compare_view(snapshot_a)
    right = _compare_view(snapshot_b)
    differences: list[str] = []
    if left.content_hash != right.content_hash:
        differences.append("content_hash")
    if left.quality_hash != right.quality_hash:
        differences.append("quality_hash")
    if left.manifest_hash != right.manifest_hash:
        differences.append("manifest_hash")
    if left.as_of != right.as_of:
        differences.append("as_of")
    if left.git_commit != right.git_commit:
        differences.append("git_commit")
    if left.package_version != right.package_version:
        differences.append("package_version")
    if left.start_time != right.start_time:
        differences.append("start_time")
    if left.end_time != right.end_time:
        differences.append("end_time")
    if left.artifact_paths != right.artifact_paths:
        differences.append("artifact_paths")
    if left.row_count != right.row_count:
        differences.append("row_count")
    if left.instrument_count != right.instrument_count:
        differences.append("instrument_count")
    if left.error_count != right.error_count:
        differences.append("error_count")
    if left.warning_count != right.warning_count:
        differences.append("warning_count")
    return DatasetSnapshotComparison(
        snapshot_a_id=left.snapshot_id,
        snapshot_b_id=right.snapshot_id,
        same_content_hash=left.content_hash == right.content_hash,
        same_quality_hash=left.quality_hash == right.quality_hash,
        same_manifest_hash=left.manifest_hash == right.manifest_hash,
        same_as_of=left.as_of == right.as_of,
        same_git_commit=left.git_commit == right.git_commit,
        same_package_version=left.package_version == right.package_version,
        same_start_time=left.start_time == right.start_time,
        same_end_time=left.end_time == right.end_time,
        same_artifact_paths=left.artifact_paths == right.artifact_paths,
        row_count_delta=right.row_count - left.row_count,
        instrument_count_delta=right.instrument_count - left.instrument_count,
        error_count_delta=right.error_count - left.error_count,
        warning_count_delta=right.warning_count - left.warning_count,
        differences=tuple(differences),
    )


def _parse_request_time(request: Mapping[str, object], field: str) -> datetime:
    raw = request.get(field)
    if not isinstance(raw, str) or not raw.strip():
        raise DatasetValidationError(
            f"dataset_request.{field} is required",
            code=DatasetErrorCode.CATALOG_INVALID,
        )
    parsed = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise DatasetValidationError(
            f"dataset_request.{field} must be timezone-aware UTC",
            code=DatasetErrorCode.NAIVE_TIMESTAMP,
        )
    return parsed


def _record_payload(manifest: DatasetSnapshotManifest) -> dict[str, object]:
    artifacts = [item.as_mapping() for item in manifest.artifacts]
    return {
        "snapshot_id": str(manifest.snapshot_id),
        "content_hash": manifest.content_hash,
        "quality_hash": manifest.quality_hash,
        "manifest_hash": manifest.manifest_hash,
        "package_version": manifest.package_version,
        "git_commit": manifest.git_commit,
        "created_at": manifest.created_at,
        "as_of": _parse_request_time(manifest.dataset_request, "as_of"),
        "start_time": _parse_request_time(manifest.dataset_request, "start_time"),
        "end_time": _parse_request_time(manifest.dataset_request, "end_time"),
        "row_count": manifest.row_count,
        "instrument_count": manifest.instrument_count,
        "warning_count": manifest.warning_count,
        "error_count": manifest.error_count,
        "is_reproducible": True,
        "is_usable": manifest.error_count == 0,
        "dataset_request": dict(manifest.dataset_request),
        "quality_summary": {
            "error_count": manifest.error_count,
            "warning_count": manifest.warning_count,
            "info_count": manifest.info_count,
            "quality_hash": manifest.quality_hash,
        },
        "artifacts": artifacts,
        "notes": manifest.notes,
    }


def _apply_payload(row: DatasetSnapshotRecord, payload: Mapping[str, object]) -> None:
    row.content_hash = str(payload["content_hash"])
    row.quality_hash = str(payload["quality_hash"])
    row.manifest_hash = str(payload["manifest_hash"])
    row.package_version = str(payload["package_version"])
    git_commit = payload["git_commit"]
    row.git_commit = str(git_commit) if git_commit is not None else None
    created_at = payload["created_at"]
    as_of = payload["as_of"]
    start_time = payload["start_time"]
    end_time = payload["end_time"]
    if not isinstance(created_at, datetime):
        raise DatasetValidationError(
            "created_at must be a datetime",
            code=DatasetErrorCode.CATALOG_INVALID,
        )
    if not isinstance(as_of, datetime) or not isinstance(start_time, datetime):
        raise DatasetValidationError(
            "as_of and start_time must be datetimes",
            code=DatasetErrorCode.CATALOG_INVALID,
        )
    if not isinstance(end_time, datetime):
        raise DatasetValidationError(
            "end_time must be a datetime",
            code=DatasetErrorCode.CATALOG_INVALID,
        )
    row.created_at = created_at
    row.as_of = as_of
    row.start_time = start_time
    row.end_time = end_time
    row.row_count = _as_int(payload["row_count"], field="row_count")
    row.instrument_count = _as_int(
        payload["instrument_count"], field="instrument_count"
    )
    row.warning_count = _as_int(payload["warning_count"], field="warning_count")
    row.error_count = _as_int(payload["error_count"], field="error_count")
    row.is_reproducible = bool(payload["is_reproducible"])
    row.is_usable = bool(payload["is_usable"])
    dataset_request = payload["dataset_request"]
    quality_summary = payload["quality_summary"]
    artifacts = payload["artifacts"]
    if not isinstance(dataset_request, dict):
        raise DatasetValidationError(
            "dataset_request must be an object",
            code=DatasetErrorCode.CATALOG_INVALID,
        )
    if not isinstance(quality_summary, dict):
        raise DatasetValidationError(
            "quality_summary must be an object",
            code=DatasetErrorCode.CATALOG_INVALID,
        )
    if not isinstance(artifacts, list):
        raise DatasetValidationError(
            "artifacts must be a list",
            code=DatasetErrorCode.CATALOG_INVALID,
        )
    artifact_rows: list[dict[str, object]] = []
    for item in artifacts:
        if not isinstance(item, dict):
            raise DatasetValidationError(
                "each artifact must be an object",
                code=DatasetErrorCode.CATALOG_INVALID,
            )
        artifact_rows.append(dict(item))
    row.dataset_request = dict(dataset_request)
    row.quality_summary = dict(quality_summary)
    row.artifacts = artifact_rows
    notes = payload["notes"]
    row.notes = str(notes) if notes is not None else None


def _as_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DatasetValidationError(
            f"{field} must be an integer",
            code=DatasetErrorCode.CATALOG_INVALID,
        )
    return value


def _entry_from_record(row: DatasetSnapshotRecord) -> DatasetSnapshotCatalogEntry:
    artifacts = tuple(dict(item) for item in row.artifacts)
    return DatasetSnapshotCatalogEntry(
        snapshot_id=row.snapshot_id,
        content_hash=row.content_hash,
        quality_hash=row.quality_hash,
        manifest_hash=row.manifest_hash,
        package_version=row.package_version,
        git_commit=row.git_commit,
        created_at=row.created_at,
        as_of=row.as_of,
        start_time=row.start_time,
        end_time=row.end_time,
        row_count=row.row_count,
        instrument_count=row.instrument_count,
        warning_count=row.warning_count,
        error_count=row.error_count,
        is_reproducible=row.is_reproducible,
        is_usable=row.is_usable,
        dataset_request=dict(row.dataset_request),
        quality_summary=dict(row.quality_summary),
        artifacts=artifacts,
        notes=row.notes,
        registered_at=row.registered_at,
    )


@dataclass(frozen=True, slots=True)
class _CompareView:
    snapshot_id: str
    content_hash: str
    quality_hash: str
    manifest_hash: str
    as_of: datetime
    start_time: datetime
    end_time: datetime
    git_commit: str | None
    package_version: str
    artifact_paths: tuple[str, ...]
    row_count: int
    instrument_count: int
    error_count: int
    warning_count: int


def _artifact_paths_from_manifest(manifest: DatasetSnapshotManifest) -> tuple[str, ...]:
    return tuple(sorted(item.path for item in manifest.artifacts))


def _artifact_paths_from_entry(entry: DatasetSnapshotCatalogEntry) -> tuple[str, ...]:
    paths: list[str] = []
    for item in entry.artifacts:
        path = item.get("path")
        if isinstance(path, str):
            paths.append(path)
    return tuple(sorted(paths))


def _compare_view(
    item: DatasetSnapshotCatalogEntry | DatasetSnapshotManifest,
) -> _CompareView:
    if isinstance(item, DatasetSnapshotManifest):
        return _CompareView(
            snapshot_id=str(item.snapshot_id),
            content_hash=item.content_hash,
            quality_hash=item.quality_hash,
            manifest_hash=item.manifest_hash,
            as_of=_parse_request_time(item.dataset_request, "as_of"),
            start_time=_parse_request_time(item.dataset_request, "start_time"),
            end_time=_parse_request_time(item.dataset_request, "end_time"),
            git_commit=item.git_commit,
            package_version=item.package_version,
            artifact_paths=_artifact_paths_from_manifest(item),
            row_count=item.row_count,
            instrument_count=item.instrument_count,
            error_count=item.error_count,
            warning_count=item.warning_count,
        )
    return _CompareView(
        snapshot_id=item.snapshot_id,
        content_hash=item.content_hash,
        quality_hash=item.quality_hash,
        manifest_hash=item.manifest_hash,
        as_of=item.as_of,
        start_time=item.start_time,
        end_time=item.end_time,
        git_commit=item.git_commit,
        package_version=item.package_version,
        artifact_paths=_artifact_paths_from_entry(item),
        row_count=item.row_count,
        instrument_count=item.instrument_count,
        error_count=item.error_count,
        warning_count=item.warning_count,
    )


def compare_catalog_snapshots(
    session: Session, snapshot_id_a: str, snapshot_id_b: str
) -> DatasetSnapshotComparison:
    """Compare two catalog rows. Does not read local files."""
    left = get_dataset_snapshot_by_id(session, snapshot_id_a)
    right = get_dataset_snapshot_by_id(session, snapshot_id_b)
    if left is None or right is None:
        raise DatasetValidationError(
            "both snapshot_id values must exist in the catalog",
            code=DatasetErrorCode.CATALOG_INVALID,
        )
    return compare_dataset_snapshots(left, right)
