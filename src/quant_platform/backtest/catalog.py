"""PostgreSQL catalog of local backtest runs. Metadata only; no orders."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from quant_platform.backtest.errors import BacktestError, BacktestErrorCode
from quant_platform.backtest.types import (
    ALLOWED_POLICY_NAMES,
    BacktestManifest,
    BacktestRunCatalogEntry,
    BacktestRunCatalogFilters,
    BacktestRunComparison,
    BacktestRunRegistration,
    artifacts_have_unsafe_paths,
    build_backtest_run_catalog_filters,
)
from quant_platform.data.models import BacktestRunRecord
from quant_platform.research.snapshots import (
    canonical_json,
    is_sha256_digest,
    manifest_contains_secrets,
)


def raise_if_manifest_hash_conflict(
    existing: BacktestRunCatalogEntry | None, manifest: BacktestManifest
) -> None:
    """Fail when the same manifest_hash is owned by another backtest_id."""
    if existing is None:
        return
    backtest_id = str(manifest.backtest_id)
    if existing.backtest_id != backtest_id:
        raise BacktestError(
            "manifest_hash already registered under a different backtest_id",
            code=BacktestErrorCode.CATALOG_CONFLICT,
        )


def validate_backtest_run_manifest(manifest: BacktestManifest) -> None:
    """Reject manifests that cannot be stored as catalog metadata."""
    if manifest.policy_name not in ALLOWED_POLICY_NAMES:
        raise BacktestError(
            "policy_name must be a registered research policy",
            code=BacktestErrorCode.INVALID_POLICY,
        )
    for label, value in (
        ("event_count", _summary_int(manifest.summary, "event_count")),
        ("market_event_count", _summary_int(manifest.summary, "market_event_count")),
        ("session_event_count", _summary_int(manifest.summary, "session_event_count")),
        (
            "corporate_action_event_count",
            _summary_int(manifest.summary, "corporate_action_event_count"),
        ),
        ("warning_count", _summary_int(manifest.summary, "warning_count")),
        ("error_count", _summary_int(manifest.summary, "error_count")),
    ):
        if value < 0:
            raise BacktestError(
                f"{label} must be >= 0",
                code=BacktestErrorCode.CATALOG_INVALID,
            )
    if not is_sha256_digest(manifest.stream_hash):
        raise BacktestError(
            "stream_hash must be a sha256:<hex> digest",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    if not is_sha256_digest(manifest.backtest_hash):
        raise BacktestError(
            "backtest_hash must be a sha256:<hex> digest",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    if not is_sha256_digest(manifest.policy_output_hash):
        raise BacktestError(
            "policy_output_hash must be a sha256:<hex> digest",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    if not is_sha256_digest(manifest.manifest_hash):
        raise BacktestError(
            "manifest_hash must be a sha256:<hex> digest",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    if not manifest.artifacts:
        raise BacktestError(
            "backtest artifacts must not be empty",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    mappings = tuple(item.as_mapping() for item in manifest.artifacts)
    if artifacts_have_unsafe_paths(mappings):
        raise BacktestError(
            "backtest artifact paths must be relative",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    blob = {
        "artifacts": [dict(item) for item in mappings],
        "request": manifest.request,
        "summary": manifest.summary,
        "policy_config": manifest.policy_config,
        "notes": manifest.notes or "",
    }
    if manifest_contains_secrets(blob):
        raise BacktestError(
            "catalog metadata must not contain secrets",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    if manifest.created_at.tzinfo is None:
        raise BacktestError(
            "created_at must be timezone-aware UTC",
            code=BacktestErrorCode.NAIVE_TIMESTAMP,
        )


def backtest_run_is_reproducible(manifest: BacktestManifest) -> bool:
    try:
        validate_backtest_run_manifest(manifest)
    except BacktestError:
        return False
    return True


def backtest_run_is_usable(manifest: BacktestManifest) -> bool:
    """True when hashes are valid and the dry-run recorded no errors."""
    return (
        backtest_run_is_reproducible(manifest)
        and _summary_int(manifest.summary, "error_count") == 0
    )


def register_backtest_run(
    session: Session, manifest: BacktestManifest
) -> BacktestRunRegistration:
    """Upsert catalog metadata by ``backtest_id``. Unique on ``manifest_hash``."""
    validate_backtest_run_manifest(manifest)
    backtest_id = str(manifest.backtest_id)
    other = get_backtest_run_by_manifest_hash(session, manifest.manifest_hash)
    raise_if_manifest_hash_conflict(other, manifest)
    existing = session.scalars(
        select(BacktestRunRecord).where(BacktestRunRecord.backtest_id == backtest_id)
    ).first()
    payload = _record_payload(manifest)
    if existing is None:
        row = BacktestRunRecord(**cast(dict[str, Any], payload))
        session.add(row)
        session.flush()
        return BacktestRunRegistration(entry=_entry_from_record(row), action="insert")
    _apply_payload(existing, payload)
    session.flush()
    return BacktestRunRegistration(entry=_entry_from_record(existing), action="update")


def get_backtest_run_by_id(
    session: Session, backtest_id: str
) -> BacktestRunCatalogEntry | None:
    stmt = select(BacktestRunRecord).where(
        BacktestRunRecord.backtest_id == backtest_id.strip()
    )
    row = session.scalars(stmt).first()
    if row is None:
        return None
    return _entry_from_record(row)


def get_backtest_run_by_manifest_hash(
    session: Session, manifest_hash: str
) -> BacktestRunCatalogEntry | None:
    stmt = select(BacktestRunRecord).where(
        BacktestRunRecord.manifest_hash == manifest_hash.strip()
    )
    row = session.scalars(stmt).first()
    if row is None:
        return None
    return _entry_from_record(row)


def list_backtest_runs(
    session: Session,
    filters: BacktestRunCatalogFilters | None = None,
) -> tuple[BacktestRunCatalogEntry, ...]:
    query = filters or build_backtest_run_catalog_filters()
    stmt = select(BacktestRunRecord)
    if query.replay_id is not None:
        stmt = stmt.where(BacktestRunRecord.replay_id == query.replay_id)
    if query.stream_hash is not None:
        stmt = stmt.where(BacktestRunRecord.stream_hash == query.stream_hash)
    if query.policy_name is not None:
        stmt = stmt.where(BacktestRunRecord.policy_name == query.policy_name)
    if query.usable_only:
        stmt = stmt.where(BacktestRunRecord.is_usable.is_(True))
    stmt = stmt.order_by(
        BacktestRunRecord.created_at.desc(),
        BacktestRunRecord.backtest_id.asc(),
    )
    return tuple(_entry_from_record(row) for row in session.scalars(stmt))


def compare_backtest_runs(
    run_a: BacktestRunCatalogEntry | BacktestManifest,
    run_b: BacktestRunCatalogEntry | BacktestManifest,
) -> BacktestRunComparison:
    left = _compare_view(run_a)
    right = _compare_view(run_b)
    differences: list[str] = []
    if left.backtest_hash != right.backtest_hash:
        differences.append("backtest_hash")
    if left.stream_hash != right.stream_hash:
        differences.append("stream_hash")
    if left.replay_id != right.replay_id:
        differences.append("replay_id")
    if left.policy_name != right.policy_name:
        differences.append("policy_name")
    if left.policy_config != right.policy_config:
        differences.append("policy_config")
    if left.policy_output_hash != right.policy_output_hash:
        differences.append("policy_output_hash")
    if left.manifest_hash != right.manifest_hash:
        differences.append("manifest_hash")
    if left.event_count != right.event_count:
        differences.append("event_count")
    if left.error_count != right.error_count:
        differences.append("error_count")
    if left.warning_count != right.warning_count:
        differences.append("warning_count")
    return BacktestRunComparison(
        backtest_a_id=left.backtest_id,
        backtest_b_id=right.backtest_id,
        same_backtest_hash=left.backtest_hash == right.backtest_hash,
        same_stream_hash=left.stream_hash == right.stream_hash,
        same_replay_id=left.replay_id == right.replay_id,
        same_policy_name=left.policy_name == right.policy_name,
        same_policy_output_hash=left.policy_output_hash == right.policy_output_hash,
        same_manifest_hash=left.manifest_hash == right.manifest_hash,
        event_count_delta=right.event_count - left.event_count,
        warning_count_delta=right.warning_count - left.warning_count,
        error_count_delta=right.error_count - left.error_count,
        differences=tuple(differences),
    )


def compare_catalog_backtest_runs(
    session: Session, backtest_id_a: str, backtest_id_b: str
) -> BacktestRunComparison:
    left = get_backtest_run_by_id(session, backtest_id_a)
    right = get_backtest_run_by_id(session, backtest_id_b)
    if left is None or right is None:
        raise BacktestError(
            "both backtest_id values must exist in the catalog",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    return compare_backtest_runs(left, right)


def _record_payload(manifest: BacktestManifest) -> dict[str, object]:
    return {
        "backtest_id": str(manifest.backtest_id),
        "replay_id": manifest.replay_id,
        "stream_hash": manifest.stream_hash,
        "backtest_hash": manifest.backtest_hash,
        "manifest_hash": manifest.manifest_hash,
        "policy_name": manifest.policy_name,
        "policy_config": dict(manifest.policy_config),
        "policy_output_hash": manifest.policy_output_hash,
        "package_version": manifest.package_version,
        "git_commit": manifest.git_commit,
        "created_at": manifest.created_at,
        "event_count": _summary_int(manifest.summary, "event_count"),
        "market_event_count": _summary_int(manifest.summary, "market_event_count"),
        "session_event_count": _summary_int(manifest.summary, "session_event_count"),
        "corporate_action_event_count": _summary_int(
            manifest.summary, "corporate_action_event_count"
        ),
        "warning_count": _summary_int(manifest.summary, "warning_count"),
        "error_count": _summary_int(manifest.summary, "error_count"),
        "is_reproducible": True,
        "is_usable": backtest_run_is_usable(manifest),
        "request": dict(manifest.request),
        "summary": dict(manifest.summary),
        "artifacts": [item.as_mapping() for item in manifest.artifacts],
        "notes": manifest.notes,
    }


def _apply_payload(row: BacktestRunRecord, payload: Mapping[str, object]) -> None:
    row.replay_id = str(payload["replay_id"])
    row.stream_hash = str(payload["stream_hash"])
    row.backtest_hash = str(payload["backtest_hash"])
    row.manifest_hash = str(payload["manifest_hash"])
    row.policy_name = str(payload["policy_name"])
    config = payload["policy_config"]
    if not isinstance(config, dict):
        raise BacktestError(
            "policy_config must be an object",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    row.policy_config = dict(config)
    output_hash = payload["policy_output_hash"]
    row.policy_output_hash = str(output_hash) if output_hash is not None else None
    row.package_version = str(payload["package_version"])
    git_commit = payload["git_commit"]
    row.git_commit = str(git_commit) if git_commit is not None else None
    created_at = payload["created_at"]
    if not isinstance(created_at, datetime):
        raise BacktestError(
            "created_at must be a datetime",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    row.created_at = created_at
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
    row.warning_count = _as_int(payload["warning_count"], field="warning_count")
    row.error_count = _as_int(payload["error_count"], field="error_count")
    row.is_reproducible = bool(payload["is_reproducible"])
    row.is_usable = bool(payload["is_usable"])
    request = payload["request"]
    summary = payload["summary"]
    artifacts = payload["artifacts"]
    if not isinstance(request, dict):
        raise BacktestError(
            "request must be an object",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    if not isinstance(summary, dict):
        raise BacktestError(
            "summary must be an object",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    if not isinstance(artifacts, list):
        raise BacktestError(
            "artifacts must be a list",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    artifact_rows: list[dict[str, object]] = []
    for item in artifacts:
        if not isinstance(item, dict):
            raise BacktestError(
                "each artifact must be an object",
                code=BacktestErrorCode.CATALOG_INVALID,
            )
        artifact_rows.append(dict(item))
    row.request = dict(request)
    row.summary = dict(summary)
    row.artifacts = artifact_rows
    notes = payload["notes"]
    row.notes = str(notes) if notes is not None else None


def _as_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise BacktestError(
            f"{field} must be an integer",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    return value


def _summary_int(summary: Mapping[str, object], field: str) -> int:
    raw = summary.get(field, 0)
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise BacktestError(
            f"summary.{field} must be an integer",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    return raw


def _entry_from_record(row: BacktestRunRecord) -> BacktestRunCatalogEntry:
    return BacktestRunCatalogEntry(
        backtest_id=row.backtest_id,
        replay_id=row.replay_id,
        stream_hash=row.stream_hash,
        backtest_hash=row.backtest_hash,
        manifest_hash=row.manifest_hash,
        policy_name=row.policy_name,
        policy_config=dict(row.policy_config),
        policy_output_hash=row.policy_output_hash,
        package_version=row.package_version,
        git_commit=row.git_commit,
        created_at=row.created_at,
        event_count=row.event_count,
        market_event_count=row.market_event_count,
        session_event_count=row.session_event_count,
        corporate_action_event_count=row.corporate_action_event_count,
        warning_count=row.warning_count,
        error_count=row.error_count,
        is_reproducible=row.is_reproducible,
        is_usable=row.is_usable,
        request=dict(row.request),
        summary=dict(row.summary),
        artifacts=tuple(dict(item) for item in row.artifacts),
        notes=row.notes,
        registered_at=row.registered_at,
    )


@dataclass(frozen=True, slots=True)
class _CompareView:
    backtest_id: str
    replay_id: str
    stream_hash: str
    backtest_hash: str
    manifest_hash: str
    policy_name: str
    policy_config: str
    policy_output_hash: str | None
    event_count: int
    error_count: int
    warning_count: int


def _compare_view(
    item: BacktestRunCatalogEntry | BacktestManifest,
) -> _CompareView:
    if isinstance(item, BacktestManifest):
        return _CompareView(
            backtest_id=str(item.backtest_id),
            replay_id=item.replay_id,
            stream_hash=item.stream_hash,
            backtest_hash=item.backtest_hash,
            manifest_hash=item.manifest_hash,
            policy_name=item.policy_name,
            policy_config=canonical_json(dict(item.policy_config)),
            policy_output_hash=item.policy_output_hash,
            event_count=_summary_int(item.summary, "event_count"),
            error_count=_summary_int(item.summary, "error_count"),
            warning_count=_summary_int(item.summary, "warning_count"),
        )
    return _CompareView(
        backtest_id=item.backtest_id,
        replay_id=item.replay_id,
        stream_hash=item.stream_hash,
        backtest_hash=item.backtest_hash,
        manifest_hash=item.manifest_hash,
        policy_name=item.policy_name,
        policy_config=canonical_json(dict(item.policy_config)),
        policy_output_hash=item.policy_output_hash,
        event_count=item.event_count,
        error_count=item.error_count,
        warning_count=item.warning_count,
    )
