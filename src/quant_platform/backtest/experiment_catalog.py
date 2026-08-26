"""PostgreSQL catalog of dry-run backtest experiments. Metadata only."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from quant_platform.backtest.errors import BacktestError, BacktestErrorCode
from quant_platform.backtest.experiment_types import (
    EXPERIMENT_VERDICT_DIFFERENT,
    EXPERIMENT_VERDICT_IDENTICAL,
    EXPERIMENT_VERDICT_SAME_RESULT,
    BacktestExperimentCatalogEntry,
    BacktestExperimentCatalogFilters,
    BacktestExperimentComparison,
    BacktestExperimentComparisonItem,
    BacktestExperimentManifest,
    BacktestExperimentRegistration,
    BacktestExperimentResult,
    build_backtest_experiment_catalog_filters,
)
from quant_platform.backtest.observations import contains_operative_language
from quant_platform.backtest.types import (
    ALLOWED_POLICY_NAMES,
    artifacts_have_unsafe_paths,
)
from quant_platform.data.models import BacktestExperimentRecord
from quant_platform.research.snapshots import (
    canonical_json,
    is_sha256_digest,
    manifest_contains_secrets,
)


def raise_if_experiment_manifest_hash_conflict(
    existing: BacktestExperimentCatalogEntry | None,
    manifest: BacktestExperimentManifest,
) -> None:
    """Fail when the same manifest_hash is owned by another experiment_id."""
    if existing is None:
        return
    if existing.experiment_id != manifest.experiment_id:
        raise BacktestError(
            "manifest_hash already registered under a different experiment_id",
            code=BacktestErrorCode.CATALOG_CONFLICT,
        )


def validate_backtest_experiment_manifest(
    manifest: BacktestExperimentManifest,
) -> None:
    """Reject experiment manifests that cannot be stored as metadata."""
    from quant_platform.backtest.experiments import hash_backtest_experiment

    if manifest.policy_name not in ALLOWED_POLICY_NAMES:
        raise BacktestError(
            "policy_name must be a registered research policy",
            code=BacktestErrorCode.INVALID_POLICY,
        )
    for label, value in (
        ("member_count", _summary_int(manifest.summary, "member_count")),
        ("usable_count", _summary_int(manifest.summary, "usable_count")),
        ("warning_count", _summary_int(manifest.summary, "warning_count")),
        ("error_count", _summary_int(manifest.summary, "error_count")),
    ):
        if value < 0:
            raise BacktestError(
                f"{label} must be >= 0",
                code=BacktestErrorCode.CATALOG_INVALID,
            )
    if not is_sha256_digest(manifest.experiment_hash):
        raise BacktestError(
            "experiment_hash must be a sha256:<hex> digest",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    if not is_sha256_digest(manifest.manifest_hash):
        raise BacktestError(
            "manifest_hash must be a sha256:<hex> digest",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    if hash_backtest_experiment(manifest) != manifest.experiment_hash:
        raise BacktestError(
            "experiment_hash does not match the experiment definition",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    if not manifest.artifacts:
        raise BacktestError(
            "experiment artifacts must not be empty",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    mappings = tuple(item.as_mapping() for item in manifest.artifacts)
    if artifacts_have_unsafe_paths(mappings):
        raise BacktestError(
            "experiment artifact paths must be relative",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    blob = {
        "artifacts": [dict(item) for item in mappings],
        "request": manifest.request,
        "summary": manifest.summary,
        "notes": manifest.notes or "",
        "description": manifest.description or "",
    }
    if manifest_contains_secrets(blob):
        raise BacktestError(
            "catalog metadata must not contain secrets",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    if contains_operative_language(canonical_json(blob)):
        raise BacktestError(
            "experiment metadata must not contain investment-decision wording",
            code=BacktestErrorCode.INVALID_POLICY,
        )
    if manifest.created_at.tzinfo is None:
        raise BacktestError(
            "created_at must be timezone-aware UTC",
            code=BacktestErrorCode.NAIVE_TIMESTAMP,
        )


def register_backtest_experiment(
    session: Session, manifest: BacktestExperimentManifest
) -> BacktestExperimentRegistration:
    """Upsert catalog metadata by ``experiment_id``. Unique on ``manifest_hash``."""
    validate_backtest_experiment_manifest(manifest)
    other = get_backtest_experiment_by_manifest_hash(session, manifest.manifest_hash)
    raise_if_experiment_manifest_hash_conflict(other, manifest)
    existing = session.scalars(
        select(BacktestExperimentRecord).where(
            BacktestExperimentRecord.experiment_id == manifest.experiment_id
        )
    ).first()
    payload = _record_payload(manifest)
    if existing is None:
        row = BacktestExperimentRecord(**cast(dict[str, Any], payload))
        session.add(row)
        session.flush()
        return BacktestExperimentRegistration(
            entry=_entry_from_record(row), action="insert"
        )
    _apply_payload(existing, payload)
    session.flush()
    return BacktestExperimentRegistration(
        entry=_entry_from_record(existing), action="update"
    )


def get_backtest_experiment_by_id(
    session: Session, experiment_id: str
) -> BacktestExperimentCatalogEntry | None:
    stmt = select(BacktestExperimentRecord).where(
        BacktestExperimentRecord.experiment_id == experiment_id.strip()
    )
    row = session.scalars(stmt).first()
    if row is None:
        return None
    return _entry_from_record(row)


def get_backtest_experiment_by_manifest_hash(
    session: Session, manifest_hash: str
) -> BacktestExperimentCatalogEntry | None:
    stmt = select(BacktestExperimentRecord).where(
        BacktestExperimentRecord.manifest_hash == manifest_hash.strip()
    )
    row = session.scalars(stmt).first()
    if row is None:
        return None
    return _entry_from_record(row)


def list_backtest_experiments(
    session: Session,
    filters: BacktestExperimentCatalogFilters | None = None,
) -> tuple[BacktestExperimentCatalogEntry, ...]:
    query = filters or build_backtest_experiment_catalog_filters()
    stmt = select(BacktestExperimentRecord)
    if query.experiment_name is not None:
        stmt = stmt.where(
            BacktestExperimentRecord.experiment_name == query.experiment_name
        )
    if query.policy_name is not None:
        stmt = stmt.where(BacktestExperimentRecord.policy_name == query.policy_name)
    if query.usable_only:
        stmt = stmt.where(
            BacktestExperimentRecord.usable_count
            == BacktestExperimentRecord.member_count,
            BacktestExperimentRecord.error_count == 0,
        )
    stmt = stmt.order_by(
        BacktestExperimentRecord.created_at.desc(),
        BacktestExperimentRecord.experiment_id.asc(),
    )
    return tuple(_entry_from_record(row) for row in session.scalars(stmt))


def compare_backtest_experiments(
    left: (
        BacktestExperimentCatalogEntry
        | BacktestExperimentManifest
        | BacktestExperimentResult
    ),
    right: (
        BacktestExperimentCatalogEntry
        | BacktestExperimentManifest
        | BacktestExperimentResult
    ),
) -> BacktestExperimentComparison:
    """Compare experiment metadata. Does not load replay events or PnL."""
    view_a = _compare_view(left)
    view_b = _compare_view(right)
    items: list[BacktestExperimentComparisonItem] = []
    _add(items, "experiment_hash", view_a.experiment_hash, view_b.experiment_hash)
    _add(items, "manifest_hash", view_a.manifest_hash, view_b.manifest_hash)
    _add(items, "experiment_name", view_a.experiment_name, view_b.experiment_name)
    _add(items, "policy_name", view_a.policy_name, view_b.policy_name)
    _add(items, "member_count", view_a.member_count, view_b.member_count)
    _add(items, "usable_count", view_a.usable_count, view_b.usable_count)
    _add(items, "error_count", view_a.error_count, view_b.error_count)
    _add(items, "warning_count", view_a.warning_count, view_b.warning_count)
    _add(items, "replay_ids", view_a.replay_ids, view_b.replay_ids)
    _add(items, "policy_configs", view_a.policy_configs, view_b.policy_configs)
    _add(items, "member_hashes", view_a.member_hashes, view_b.member_hashes)
    ranked = tuple(sorted(items, key=lambda item: (item.field, item.code)))
    same_hash = view_a.experiment_hash == view_b.experiment_hash
    same_manifest = view_a.manifest_hash == view_b.manifest_hash
    if same_manifest:
        verdict = EXPERIMENT_VERDICT_IDENTICAL
    elif same_hash:
        verdict = EXPERIMENT_VERDICT_SAME_RESULT
    else:
        verdict = EXPERIMENT_VERDICT_DIFFERENT
    return BacktestExperimentComparison(
        experiment_a_id=view_a.experiment_id,
        experiment_b_id=view_b.experiment_id,
        same_experiment_hash=same_hash,
        same_manifest_hash=same_manifest,
        identical=same_manifest,
        verdict=verdict,
        items=ranked,
    )


def compare_catalog_backtest_experiments(
    session: Session, experiment_id_a: str, experiment_id_b: str
) -> BacktestExperimentComparison:
    left = get_backtest_experiment_by_id(session, experiment_id_a)
    right = get_backtest_experiment_by_id(session, experiment_id_b)
    if left is None or right is None:
        raise BacktestError(
            "both experiment_id values must exist in the catalog",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    return compare_backtest_experiments(left, right)


def _record_payload(manifest: BacktestExperimentManifest) -> dict[str, object]:
    return {
        "experiment_id": manifest.experiment_id,
        "experiment_name": manifest.experiment_name,
        "experiment_hash": manifest.experiment_hash,
        "manifest_hash": manifest.manifest_hash,
        "policy_name": manifest.policy_name,
        "package_version": manifest.package_version,
        "git_commit": manifest.git_commit,
        "created_at": manifest.created_at,
        "member_count": _summary_int(manifest.summary, "member_count"),
        "usable_count": _summary_int(manifest.summary, "usable_count"),
        "error_count": _summary_int(manifest.summary, "error_count"),
        "warning_count": _summary_int(manifest.summary, "warning_count"),
        "request": dict(manifest.request),
        "summary": dict(manifest.summary),
        "artifacts": [item.as_mapping() for item in manifest.artifacts],
        "notes": manifest.notes,
    }


def _apply_payload(
    row: BacktestExperimentRecord, payload: Mapping[str, object]
) -> None:
    row.experiment_name = str(payload["experiment_name"])
    row.experiment_hash = str(payload["experiment_hash"])
    row.manifest_hash = str(payload["manifest_hash"])
    row.policy_name = str(payload["policy_name"])
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
    row.member_count = _as_int(payload["member_count"], field="member_count")
    row.usable_count = _as_int(payload["usable_count"], field="usable_count")
    row.error_count = _as_int(payload["error_count"], field="error_count")
    row.warning_count = _as_int(payload["warning_count"], field="warning_count")
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


def _entry_from_record(row: BacktestExperimentRecord) -> BacktestExperimentCatalogEntry:
    return BacktestExperimentCatalogEntry(
        experiment_id=row.experiment_id,
        experiment_name=row.experiment_name,
        experiment_hash=row.experiment_hash,
        manifest_hash=row.manifest_hash,
        policy_name=row.policy_name,
        package_version=row.package_version,
        git_commit=row.git_commit,
        created_at=row.created_at,
        member_count=row.member_count,
        usable_count=row.usable_count,
        error_count=row.error_count,
        warning_count=row.warning_count,
        request=dict(row.request),
        summary=dict(row.summary),
        artifacts=tuple(dict(item) for item in row.artifacts),
        notes=row.notes,
        registered_at=row.registered_at,
    )


@dataclass(frozen=True, slots=True)
class _CompareView:
    experiment_id: str
    experiment_name: str
    experiment_hash: str
    manifest_hash: str
    policy_name: str
    member_count: str
    usable_count: str
    error_count: str
    warning_count: str
    replay_ids: str
    policy_configs: str
    member_hashes: str


def _compare_view(
    item: (
        BacktestExperimentCatalogEntry
        | BacktestExperimentManifest
        | BacktestExperimentResult
    ),
) -> _CompareView:
    if isinstance(item, BacktestExperimentResult):
        if item.manifest is not None:
            return _compare_view(item.manifest)
        return _CompareView(
            experiment_id=item.summary.experiment_id,
            experiment_name=item.summary.experiment_name,
            experiment_hash=item.summary.experiment_hash,
            manifest_hash="",
            policy_name=item.summary.policy_name,
            member_count=str(item.summary.member_count),
            usable_count=str(item.summary.usable_count),
            error_count=str(item.summary.error_count),
            warning_count=str(item.summary.warning_count),
            replay_ids=canonical_json(sorted(item.summary.replay_ids)),
            policy_configs=canonical_json(
                sorted(
                    [dict(cfg) for cfg in item.summary.policy_configs],
                    key=canonical_json,
                )
            ),
            member_hashes=canonical_json(
                sorted(member.backtest_hash for member in item.members)
            ),
        )
    if isinstance(item, BacktestExperimentManifest):
        summary = item.summary
        return _CompareView(
            experiment_id=item.experiment_id,
            experiment_name=item.experiment_name,
            experiment_hash=item.experiment_hash,
            manifest_hash=item.manifest_hash,
            policy_name=item.policy_name,
            member_count=str(_summary_int(summary, "member_count")),
            usable_count=str(_summary_int(summary, "usable_count")),
            error_count=str(_summary_int(summary, "error_count")),
            warning_count=str(_summary_int(summary, "warning_count")),
            replay_ids=_canonical_string_list(summary.get("replay_ids")),
            policy_configs=_canonical_config_list(summary.get("policy_configs")),
            member_hashes=_canonical_member_hashes(summary.get("members")),
        )
    return _CompareView(
        experiment_id=item.experiment_id,
        experiment_name=item.experiment_name,
        experiment_hash=item.experiment_hash,
        manifest_hash=item.manifest_hash,
        policy_name=item.policy_name,
        member_count=str(item.member_count),
        usable_count=str(item.usable_count),
        error_count=str(item.error_count),
        warning_count=str(item.warning_count),
        replay_ids=_canonical_string_list(item.summary.get("replay_ids")),
        policy_configs=_canonical_config_list(item.summary.get("policy_configs")),
        member_hashes=_canonical_member_hashes(item.summary.get("members")),
    )


def _canonical_string_list(value: object) -> str:
    if not isinstance(value, list):
        return canonical_json([])
    items = [str(item) for item in value]
    return canonical_json(sorted(items))


def _canonical_config_list(value: object) -> str:
    if not isinstance(value, list):
        return canonical_json([])
    configs = [dict(item) for item in value if isinstance(item, dict)]
    return canonical_json(sorted(configs, key=canonical_json))


def _canonical_member_hashes(value: object) -> str:
    if not isinstance(value, list):
        return canonical_json([])
    hashes: list[str] = []
    for item in value:
        if isinstance(item, dict):
            digest = item.get("backtest_hash")
            if isinstance(digest, str):
                hashes.append(digest)
    return canonical_json(sorted(hashes))


def _add(
    items: list[BacktestExperimentComparisonItem],
    field: str,
    left: str | None,
    right: str | None,
) -> None:
    if left != right:
        items.append(
            BacktestExperimentComparisonItem(
                field=field,
                code=f"{field}_diff",
                left=left,
                right=right,
            )
        )
