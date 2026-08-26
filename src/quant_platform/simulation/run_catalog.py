"""PostgreSQL catalog of local replay runs. Metadata only; no event rows."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from quant_platform.data.models import SimulationReplayRunRecord
from quant_platform.research.snapshots import (
    is_sha256_digest,
    manifest_contains_secrets,
)
from quant_platform.simulation.errors import SimulationError, SimulationErrorCode
from quant_platform.simulation.run_types import (
    SOURCE_TYPES,
    ReplayRunCatalogEntry,
    ReplayRunCatalogFilters,
    ReplayRunComparison,
    ReplayRunManifest,
    ReplayRunRegistration,
    artifacts_have_unsafe_paths,
    build_replay_run_catalog_filters,
)


def raise_if_manifest_hash_conflict(
    existing: ReplayRunCatalogEntry | None, manifest: ReplayRunManifest
) -> None:
    """Fail when the same manifest_hash is owned by another replay_id."""
    if existing is None:
        return
    replay_id = str(manifest.replay_id)
    if existing.replay_id != replay_id:
        raise SimulationError(
            "manifest_hash already registered under a different replay_id",
            code=SimulationErrorCode.CATALOG_CONFLICT,
        )


def validate_replay_run_manifest(manifest: ReplayRunManifest) -> None:
    """Reject manifests that cannot be stored as catalog metadata."""
    if manifest.source_type not in SOURCE_TYPES:
        raise SimulationError(
            "source_type must be 'database' or 'snapshot'",
            code=SimulationErrorCode.CATALOG_INVALID,
        )
    for label, value in (
        ("event_count", manifest.event_count),
        ("pre_known_event_count", manifest.pre_known_event_count),
        ("warning_count", manifest.warning_count),
        ("error_count", manifest.error_count),
    ):
        if value < 0:
            raise SimulationError(
                f"{label} must be >= 0",
                code=SimulationErrorCode.CATALOG_INVALID,
            )
    if not is_sha256_digest(manifest.stream_hash):
        raise SimulationError(
            "stream_hash must be a sha256:<hex> digest",
            code=SimulationErrorCode.CATALOG_INVALID,
        )
    if not is_sha256_digest(manifest.manifest_hash):
        raise SimulationError(
            "manifest_hash must be a sha256:<hex> digest",
            code=SimulationErrorCode.CATALOG_INVALID,
        )
    if manifest.dataset_content_hash is not None and not is_sha256_digest(
        manifest.dataset_content_hash
    ):
        raise SimulationError(
            "dataset_content_hash must be a sha256:<hex> digest",
            code=SimulationErrorCode.CATALOG_INVALID,
        )
    if not manifest.artifacts:
        raise SimulationError(
            "replay artifacts must not be empty",
            code=SimulationErrorCode.CATALOG_INVALID,
        )
    mappings = tuple(item.as_mapping() for item in manifest.artifacts)
    if artifacts_have_unsafe_paths(mappings):
        raise SimulationError(
            "replay artifact paths must be relative",
            code=SimulationErrorCode.CATALOG_INVALID,
        )
    blob = {
        "artifacts": [dict(item) for item in mappings],
        "request": manifest.request,
        "notes": manifest.notes or "",
        "audit_summary": dict(manifest.audit_summary),
    }
    if manifest_contains_secrets(blob):
        raise SimulationError(
            "catalog metadata must not contain secrets",
            code=SimulationErrorCode.CATALOG_INVALID,
        )
    if manifest.created_at.tzinfo is None:
        raise SimulationError(
            "created_at must be timezone-aware UTC",
            code=SimulationErrorCode.NAIVE_TIMESTAMP,
        )


def replay_run_is_reproducible(manifest: ReplayRunManifest) -> bool:
    try:
        validate_replay_run_manifest(manifest)
    except SimulationError:
        return False
    return True


def replay_run_is_usable(manifest: ReplayRunManifest) -> bool:
    """True when hashes are valid, audit has no errors, and the boundary holds."""
    return (
        replay_run_is_reproducible(manifest)
        and manifest.error_count == 0
        and manifest.boundary_ok
    )


def register_replay_run(
    session: Session,
    manifest: ReplayRunManifest,
    base_path: Path | str | None = None,
) -> ReplayRunRegistration:
    """Upsert catalog metadata by ``replay_id``. Unique on ``manifest_hash``.

    ``base_path`` is not stored (absolute directories would leak local paths).
    """
    del base_path
    validate_replay_run_manifest(manifest)
    replay_id = str(manifest.replay_id)
    other = get_replay_run_by_manifest_hash(session, manifest.manifest_hash)
    raise_if_manifest_hash_conflict(other, manifest)
    existing = session.scalars(
        select(SimulationReplayRunRecord).where(
            SimulationReplayRunRecord.replay_id == replay_id
        )
    ).first()
    payload = _record_payload(manifest)
    if existing is None:
        row = SimulationReplayRunRecord(**cast(dict[str, Any], payload))
        session.add(row)
        session.flush()
        return ReplayRunRegistration(entry=_entry_from_record(row), action="insert")
    _apply_payload(existing, payload)
    session.flush()
    return ReplayRunRegistration(entry=_entry_from_record(existing), action="update")


def get_replay_run_by_id(
    session: Session, replay_id: str
) -> ReplayRunCatalogEntry | None:
    stmt = select(SimulationReplayRunRecord).where(
        SimulationReplayRunRecord.replay_id == replay_id.strip()
    )
    row = session.scalars(stmt).first()
    if row is None:
        return None
    return _entry_from_record(row)


def get_replay_run_by_manifest_hash(
    session: Session, manifest_hash: str
) -> ReplayRunCatalogEntry | None:
    stmt = select(SimulationReplayRunRecord).where(
        SimulationReplayRunRecord.manifest_hash == manifest_hash.strip()
    )
    row = session.scalars(stmt).first()
    if row is None:
        return None
    return _entry_from_record(row)


def list_replay_runs(
    session: Session,
    filters: ReplayRunCatalogFilters | None = None,
) -> tuple[ReplayRunCatalogEntry, ...]:
    query = filters or build_replay_run_catalog_filters()
    stmt = select(SimulationReplayRunRecord)
    if query.stream_hash is not None:
        stmt = stmt.where(SimulationReplayRunRecord.stream_hash == query.stream_hash)
    if query.source_type is not None:
        stmt = stmt.where(SimulationReplayRunRecord.source_type == query.source_type)
    if query.dataset_snapshot_id is not None:
        stmt = stmt.where(
            SimulationReplayRunRecord.dataset_snapshot_id == query.dataset_snapshot_id
        )
    if query.usable_only:
        stmt = stmt.where(SimulationReplayRunRecord.is_usable.is_(True))
    if query.boundary_ok is not None:
        stmt = stmt.where(SimulationReplayRunRecord.boundary_ok.is_(query.boundary_ok))
    stmt = stmt.order_by(
        SimulationReplayRunRecord.created_at.desc(),
        SimulationReplayRunRecord.replay_id.asc(),
    )
    return tuple(_entry_from_record(row) for row in session.scalars(stmt))


def compare_replay_runs(
    run_a: ReplayRunCatalogEntry | ReplayRunManifest,
    run_b: ReplayRunCatalogEntry | ReplayRunManifest,
) -> ReplayRunComparison:
    left = _compare_view(run_a)
    right = _compare_view(run_b)
    differences: list[str] = []
    if left.stream_hash != right.stream_hash:
        differences.append("stream_hash")
    if left.manifest_hash != right.manifest_hash:
        differences.append("manifest_hash")
    if left.source_type != right.source_type:
        differences.append("source_type")
    if left.boundary_ok != right.boundary_ok:
        differences.append("boundary_ok")
    if left.package_version != right.package_version:
        differences.append("package_version")
    if left.git_commit != right.git_commit:
        differences.append("git_commit")
    if left.dataset_snapshot_id != right.dataset_snapshot_id:
        differences.append("dataset_snapshot_id")
    if left.dataset_content_hash != right.dataset_content_hash:
        differences.append("dataset_content_hash")
    if left.artifact_paths != right.artifact_paths:
        differences.append("artifact_paths")
    if left.event_count != right.event_count:
        differences.append("event_count")
    if left.error_count != right.error_count:
        differences.append("error_count")
    if left.warning_count != right.warning_count:
        differences.append("warning_count")
    if left.pre_known_event_count != right.pre_known_event_count:
        differences.append("pre_known_event_count")
    return ReplayRunComparison(
        replay_a_id=left.replay_id,
        replay_b_id=right.replay_id,
        same_stream_hash=left.stream_hash == right.stream_hash,
        same_manifest_hash=left.manifest_hash == right.manifest_hash,
        same_source_type=left.source_type == right.source_type,
        same_boundary_ok=left.boundary_ok == right.boundary_ok,
        same_package_version=left.package_version == right.package_version,
        same_git_commit=left.git_commit == right.git_commit,
        same_dataset_snapshot_id=left.dataset_snapshot_id == right.dataset_snapshot_id,
        same_dataset_content_hash=(
            left.dataset_content_hash == right.dataset_content_hash
        ),
        same_artifact_paths=left.artifact_paths == right.artifact_paths,
        event_count_delta=right.event_count - left.event_count,
        error_count_delta=right.error_count - left.error_count,
        warning_count_delta=right.warning_count - left.warning_count,
        pre_known_event_count_delta=(
            right.pre_known_event_count - left.pre_known_event_count
        ),
        differences=tuple(differences),
    )


def compare_catalog_replay_runs(
    session: Session, replay_id_a: str, replay_id_b: str
) -> ReplayRunComparison:
    left = get_replay_run_by_id(session, replay_id_a)
    right = get_replay_run_by_id(session, replay_id_b)
    if left is None or right is None:
        raise SimulationError(
            "both replay_id values must exist in the catalog",
            code=SimulationErrorCode.CATALOG_INVALID,
        )
    return compare_replay_runs(left, right)


def _record_payload(manifest: ReplayRunManifest) -> dict[str, object]:
    request = dict(manifest.request)
    return {
        "replay_id": str(manifest.replay_id),
        "stream_hash": manifest.stream_hash,
        "manifest_hash": manifest.manifest_hash,
        "source_type": manifest.source_type,
        "dataset_snapshot_id": manifest.dataset_snapshot_id,
        "dataset_content_hash": manifest.dataset_content_hash,
        "package_version": manifest.package_version,
        "git_commit": manifest.git_commit,
        "created_at": manifest.created_at,
        "as_of": _optional_request_time(request, "as_of"),
        "start_time": _optional_request_time(request, "start_time"),
        "end_time": _optional_request_time(request, "end_time"),
        "event_count": manifest.event_count,
        "market_event_count": manifest.event_counts_by_type.get("market_bar", 0),
        "session_event_count": manifest.event_counts_by_type.get("market_session", 0),
        "corporate_action_event_count": manifest.event_counts_by_type.get(
            "corporate_action", 0
        ),
        "pre_known_event_count": manifest.pre_known_event_count,
        "warning_count": manifest.warning_count,
        "error_count": manifest.error_count,
        "boundary_ok": manifest.boundary_ok,
        "is_reproducible": True,
        "is_usable": replay_run_is_usable(manifest),
        "request": request,
        "audit_summary": dict(manifest.audit_summary),
        "artifacts": [item.as_mapping() for item in manifest.artifacts],
        "notes": manifest.notes,
    }


def _optional_request_time(
    request: Mapping[str, object], field: str
) -> datetime | None:
    raw = request.get(field)
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw.strip():
        return None
    parsed = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise SimulationError(
            f"request.{field} must be timezone-aware UTC",
            code=SimulationErrorCode.NAIVE_TIMESTAMP,
        )
    return parsed


def _apply_payload(
    row: SimulationReplayRunRecord, payload: Mapping[str, object]
) -> None:
    row.stream_hash = str(payload["stream_hash"])
    row.manifest_hash = str(payload["manifest_hash"])
    row.source_type = str(payload["source_type"])
    snapshot_id = payload["dataset_snapshot_id"]
    row.dataset_snapshot_id = str(snapshot_id) if snapshot_id is not None else None
    content_hash = payload["dataset_content_hash"]
    row.dataset_content_hash = str(content_hash) if content_hash is not None else None
    row.package_version = str(payload["package_version"])
    git_commit = payload["git_commit"]
    row.git_commit = str(git_commit) if git_commit is not None else None
    created_at = payload["created_at"]
    if not isinstance(created_at, datetime):
        raise SimulationError(
            "created_at must be a datetime",
            code=SimulationErrorCode.CATALOG_INVALID,
        )
    row.created_at = created_at
    row.as_of = _optional_datetime(payload["as_of"], field="as_of")
    row.start_time = _optional_datetime(payload["start_time"], field="start_time")
    row.end_time = _optional_datetime(payload["end_time"], field="end_time")
    row.event_count = _as_int(payload["event_count"], field="event_count")
    row.market_event_count = _as_int(
        payload["market_event_count"], field="market_event_count"
    )
    row.session_event_count = _as_int(
        payload["session_event_count"], field="session_event_count"
    )
    row.corporate_action_event_count = _as_int(
        payload["corporate_action_event_count"],
        field="corporate_action_event_count",
    )
    row.pre_known_event_count = _as_int(
        payload["pre_known_event_count"], field="pre_known_event_count"
    )
    row.warning_count = _as_int(payload["warning_count"], field="warning_count")
    row.error_count = _as_int(payload["error_count"], field="error_count")
    row.boundary_ok = bool(payload["boundary_ok"])
    row.is_reproducible = bool(payload["is_reproducible"])
    row.is_usable = bool(payload["is_usable"])
    request = payload["request"]
    audit_summary = payload["audit_summary"]
    artifacts = payload["artifacts"]
    if not isinstance(request, dict):
        raise SimulationError(
            "request must be an object",
            code=SimulationErrorCode.CATALOG_INVALID,
        )
    if not isinstance(audit_summary, dict):
        raise SimulationError(
            "audit_summary must be an object",
            code=SimulationErrorCode.CATALOG_INVALID,
        )
    if not isinstance(artifacts, list):
        raise SimulationError(
            "artifacts must be a list",
            code=SimulationErrorCode.CATALOG_INVALID,
        )
    artifact_rows: list[dict[str, object]] = []
    for item in artifacts:
        if not isinstance(item, dict):
            raise SimulationError(
                "each artifact must be an object",
                code=SimulationErrorCode.CATALOG_INVALID,
            )
        artifact_rows.append(dict(item))
    row.request = dict(request)
    row.audit_summary = dict(audit_summary)
    row.artifacts = artifact_rows
    notes = payload["notes"]
    row.notes = str(notes) if notes is not None else None


def _optional_datetime(value: object, *, field: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise SimulationError(
            f"{field} must be a datetime",
            code=SimulationErrorCode.CATALOG_INVALID,
        )
    return value


def _as_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SimulationError(
            f"{field} must be an integer",
            code=SimulationErrorCode.CATALOG_INVALID,
        )
    return value


def _entry_from_record(row: SimulationReplayRunRecord) -> ReplayRunCatalogEntry:
    return ReplayRunCatalogEntry(
        replay_id=row.replay_id,
        stream_hash=row.stream_hash,
        manifest_hash=row.manifest_hash,
        source_type=row.source_type,
        dataset_snapshot_id=row.dataset_snapshot_id,
        dataset_content_hash=row.dataset_content_hash,
        package_version=row.package_version,
        git_commit=row.git_commit,
        created_at=row.created_at,
        as_of=row.as_of,
        start_time=row.start_time,
        end_time=row.end_time,
        event_count=row.event_count,
        market_event_count=row.market_event_count,
        session_event_count=row.session_event_count,
        corporate_action_event_count=row.corporate_action_event_count,
        pre_known_event_count=row.pre_known_event_count,
        warning_count=row.warning_count,
        error_count=row.error_count,
        boundary_ok=row.boundary_ok,
        is_reproducible=row.is_reproducible,
        is_usable=row.is_usable,
        request=dict(row.request),
        audit_summary=dict(row.audit_summary),
        artifacts=tuple(dict(item) for item in row.artifacts),
        notes=row.notes,
        registered_at=row.registered_at,
    )


@dataclass(frozen=True, slots=True)
class _CompareView:
    replay_id: str
    stream_hash: str
    manifest_hash: str
    source_type: str
    boundary_ok: bool
    package_version: str
    git_commit: str | None
    dataset_snapshot_id: str | None
    dataset_content_hash: str | None
    artifact_paths: tuple[str, ...]
    event_count: int
    error_count: int
    warning_count: int
    pre_known_event_count: int


def _artifact_paths_from_manifest(manifest: ReplayRunManifest) -> tuple[str, ...]:
    return tuple(sorted(item.path for item in manifest.artifacts))


def _artifact_paths_from_entry(entry: ReplayRunCatalogEntry) -> tuple[str, ...]:
    paths: list[str] = []
    for item in entry.artifacts:
        path = item.get("path")
        if isinstance(path, str):
            paths.append(path)
    return tuple(sorted(paths))


def _compare_view(
    item: ReplayRunCatalogEntry | ReplayRunManifest,
) -> _CompareView:
    if isinstance(item, ReplayRunManifest):
        return _CompareView(
            replay_id=str(item.replay_id),
            stream_hash=item.stream_hash,
            manifest_hash=item.manifest_hash,
            source_type=item.source_type,
            boundary_ok=item.boundary_ok,
            package_version=item.package_version,
            git_commit=item.git_commit,
            dataset_snapshot_id=item.dataset_snapshot_id,
            dataset_content_hash=item.dataset_content_hash,
            artifact_paths=_artifact_paths_from_manifest(item),
            event_count=item.event_count,
            error_count=item.error_count,
            warning_count=item.warning_count,
            pre_known_event_count=item.pre_known_event_count,
        )
    return _CompareView(
        replay_id=item.replay_id,
        stream_hash=item.stream_hash,
        manifest_hash=item.manifest_hash,
        source_type=item.source_type,
        boundary_ok=item.boundary_ok,
        package_version=item.package_version,
        git_commit=item.git_commit,
        dataset_snapshot_id=item.dataset_snapshot_id,
        dataset_content_hash=item.dataset_content_hash,
        artifact_paths=_artifact_paths_from_entry(item),
        event_count=item.event_count,
        error_count=item.error_count,
        warning_count=item.warning_count,
        pre_known_event_count=item.pre_known_event_count,
    )
