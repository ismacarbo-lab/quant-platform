"""PostgreSQL catalog of local normalized datasets. Metadata only."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from quant_platform.core.redact import redact_secret_text
from quant_platform.core.time import utc_now
from quant_platform.data.models import NormalizedDatasetRecord
from quant_platform.research.normalization.catalog_types import (
    ALLOWED_SOURCE_TYPES,
    COMPARISON_DIFFERENT,
    COMPARISON_IDENTICAL,
    COMPARISON_SAME_DATASET,
    SOURCE_LOCAL_ARTIFACTS,
    SOURCE_REPLAY,
    SOURCE_SNAPSHOT,
    NormalizedDatasetCatalogEntry,
    NormalizedDatasetCatalogFilters,
    NormalizedDatasetComparison,
    NormalizedDatasetRegistration,
    NormalizedDatasetUsabilityCode,
    NormalizedDatasetUsabilityIssue,
    NormalizedDatasetUsabilityReport,
    NormalizedDatasetUsabilitySeverity,
    artifacts_have_absolute_paths,
    build_normalized_dataset_catalog_filters,
)
from quant_platform.research.normalization.errors import (
    NormalizationError,
    NormalizationErrorCode,
)
from quant_platform.research.normalization.integrity import (
    NormalizationIntegrityCode,
    verify_normalization_artifacts,
)
from quant_platform.research.normalization.types import (
    MANIFEST_ARTIFACT_NAME,
    NormalizationManifest,
    NormalizedDailyBar,
    NormalizedDailyBarsDataset,
)
from quant_platform.research.snapshots import (
    canonical_datetime,
    canonical_json,
    is_sha256_digest,
    manifest_contains_secrets,
    sha256_canonical,
)
from quant_platform.simulation.run_types import artifact_path_is_unsafe

_ONE = Decimal("1")
_CATALOG_HASH_KIND = "normalized_dataset_catalog"
_CATALOG_HASH_VERSION = 1
_FORBIDDEN_METRIC_TOKENS = (
    "sharpe",
    "drawdown",
    "hit_ratio",
    "hit ratio",
    "pnl",
    "returns",
)
_MISSING_INTEGRITY_CODES = frozenset(
    {
        NormalizationIntegrityCode.MISSING_RUN_DIR.value,
        NormalizationIntegrityCode.MISSING_MANIFEST.value,
        NormalizationIntegrityCode.MISSING_REPORT.value,
        NormalizationIntegrityCode.MISSING_CSV.value,
    }
)


def build_normalized_dataset_registration(
    dataset: NormalizedDailyBarsDataset,
    manifest: NormalizationManifest,
    *,
    normalized_dataset_id: str | None = None,
    deterministic_id: bool = False,
    source_type: str | None = None,
    source_snapshot_id: str | None = None,
    source_replay_id: str | None = None,
    notes: str | None = None,
    created_at: datetime | None = None,
) -> NormalizedDatasetCatalogEntry:
    """Build catalog metadata from a derived dataset. Does not write PostgreSQL."""
    artifacts = tuple(item.as_mapping() for item in manifest.artifacts)
    request = _request_mapping(dataset)
    report_summary = _report_summary(dataset, manifest)
    as_of = dataset.request.as_of
    start_time = dataset.request.start_time
    end_time = dataset.request.end_time
    stamp = created_at if created_at is not None else manifest.created_at or utc_now()
    if stamp.tzinfo is None:
        raise NormalizationError(
            "created_at must be timezone-aware UTC",
            code=NormalizationErrorCode.NAIVE_TIMESTAMP,
        )
    source = _resolve_source_type(
        source_type,
        source_snapshot_id=source_snapshot_id,
        source_replay_id=source_replay_id,
    )
    dataset_hash = dataset.dataset_hash
    raw_hash = dataset.raw_dataset_hash or None
    catalog_id = _resolve_id(
        normalized_dataset_id,
        deterministic=deterministic_id,
        dataset_hash=dataset_hash,
        adjustment_mode=dataset.request.adjustment_mode.value,
        as_of=as_of,
    )
    manifest_hash = hash_normalized_dataset_catalog_manifest(
        dataset_hash=dataset_hash,
        raw_dataset_hash=raw_hash,
        adjustment_mode=dataset.request.adjustment_mode.value,
        as_of=as_of,
        start_time=start_time,
        end_time=end_time,
        symbol_count=_symbol_count(dataset),
        bar_count=len(dataset.rows),
        adjusted_bar_count=_adjusted_bar_count(dataset.rows),
        applied_action_count=dataset.report.applied_action_count,
        warning_count=dataset.report.warning_count,
        error_count=dataset.report.error_count,
        artifacts=artifacts,
        request=request,
        report_summary=report_summary,
        source_type=source,
        source_snapshot_id=source_snapshot_id,
        source_replay_id=source_replay_id,
    )
    entry = NormalizedDatasetCatalogEntry(
        normalized_dataset_id=catalog_id,
        dataset_hash=dataset_hash,
        raw_dataset_hash=raw_hash,
        source_type=source,
        source_snapshot_id=_optional_text(source_snapshot_id),
        source_replay_id=_optional_text(source_replay_id),
        adjustment_mode=dataset.request.adjustment_mode.value,
        as_of=as_of,
        start_time=start_time,
        end_time=end_time,
        symbol_count=_symbol_count(dataset),
        bar_count=len(dataset.rows),
        adjusted_bar_count=_adjusted_bar_count(dataset.rows),
        applied_action_count=dataset.report.applied_action_count,
        warning_count=dataset.report.warning_count,
        error_count=dataset.report.error_count,
        is_reproducible=True,
        is_usable=dataset.report.error_count == 0,
        artifacts=artifacts,
        request=request,
        report_summary=report_summary,
        manifest_hash=manifest_hash,
        package_version=manifest.package_version,
        git_commit=manifest.git_commit,
        created_at=stamp,
        registered_at=stamp,
        notes=_optional_text(notes),
    )
    validate_normalized_dataset_entry(entry)
    return entry


def hash_normalized_dataset_catalog_manifest(
    *,
    dataset_hash: str,
    raw_dataset_hash: str | None,
    adjustment_mode: str,
    as_of: datetime,
    start_time: datetime,
    end_time: datetime,
    symbol_count: int,
    bar_count: int,
    adjusted_bar_count: int,
    applied_action_count: int,
    warning_count: int,
    error_count: int,
    artifacts: Sequence[Mapping[str, object]],
    request: Mapping[str, object],
    report_summary: Mapping[str, object],
    source_type: str,
    source_snapshot_id: str | None,
    source_replay_id: str | None,
) -> str:
    """SHA-256 of catalog identity. No wall-clock, notes, or absolute paths."""
    payload = {
        "kind": _CATALOG_HASH_KIND,
        "version": _CATALOG_HASH_VERSION,
        "dataset_hash": dataset_hash,
        "raw_dataset_hash": raw_dataset_hash,
        "adjustment_mode": adjustment_mode,
        "as_of": canonical_datetime(as_of),
        "start_time": canonical_datetime(start_time),
        "end_time": canonical_datetime(end_time),
        "symbol_count": symbol_count,
        "bar_count": bar_count,
        "adjusted_bar_count": adjusted_bar_count,
        "applied_action_count": applied_action_count,
        "warning_count": warning_count,
        "error_count": error_count,
        "artifacts": [
            {
                "name": item.get("name"),
                "path": item.get("path"),
                "kind": item.get("kind"),
            }
            for item in sorted(artifacts, key=lambda row: str(row.get("path") or ""))
        ],
        "request": dict(request),
        "report_summary": dict(report_summary),
        "source_type": source_type,
        "source_snapshot_id": source_snapshot_id,
        "source_replay_id": source_replay_id,
    }
    blob = canonical_json(payload)
    if manifest_contains_secrets(blob):
        raise NormalizationError(
            "normalized dataset catalog hash must not contain secrets",
            code=NormalizationErrorCode.SECRET_LIKE_VALUE,
        )
    return sha256_canonical(payload)


def deterministic_normalized_dataset_id(
    *,
    dataset_hash: str,
    adjustment_mode: str,
    as_of: datetime,
) -> str:
    """Stable UUID derived from dataset identity. Not a random runtime id."""
    token = f"{dataset_hash}|{adjustment_mode}|{canonical_datetime(as_of)}"
    digest = hashlib.sha256(token.encode("utf-8")).digest()
    return str(UUID(bytes=digest[:16]))


def validate_normalized_dataset_entry(entry: NormalizedDatasetCatalogEntry) -> None:
    """Reject catalog metadata that cannot be stored."""
    if not entry.normalized_dataset_id.strip():
        raise NormalizationError(
            "normalized_dataset_id is required",
            code=NormalizationErrorCode.CATALOG_INVALID,
        )
    if entry.source_type not in ALLOWED_SOURCE_TYPES:
        raise NormalizationError(
            "source_type is not a catalog source",
            code=NormalizationErrorCode.CATALOG_INVALID,
        )
    for field, value in (
        ("bar_count", entry.bar_count),
        ("symbol_count", entry.symbol_count),
        ("adjusted_bar_count", entry.adjusted_bar_count),
        ("applied_action_count", entry.applied_action_count),
        ("warning_count", entry.warning_count),
        ("error_count", entry.error_count),
    ):
        if value < 0:
            raise NormalizationError(
                f"{field} must be >= 0",
                code=NormalizationErrorCode.CATALOG_INVALID,
            )
    if not is_sha256_digest(entry.dataset_hash):
        raise NormalizationError(
            "dataset_hash must be a sha256:<hex> digest",
            code=NormalizationErrorCode.CATALOG_INVALID,
        )
    if entry.raw_dataset_hash is not None and not is_sha256_digest(
        entry.raw_dataset_hash
    ):
        raise NormalizationError(
            "raw_dataset_hash must be a sha256:<hex> digest",
            code=NormalizationErrorCode.CATALOG_INVALID,
        )
    if not is_sha256_digest(entry.manifest_hash):
        raise NormalizationError(
            "manifest_hash must be a sha256:<hex> digest",
            code=NormalizationErrorCode.CATALOG_INVALID,
        )
    if not entry.artifacts:
        raise NormalizationError(
            "normalized dataset artifacts must not be empty",
            code=NormalizationErrorCode.CATALOG_INVALID,
        )
    if artifacts_have_absolute_paths(entry.artifacts):
        raise NormalizationError(
            "normalized dataset artifact paths must be relative",
            code=NormalizationErrorCode.CATALOG_INVALID,
        )
    for item in entry.artifacts:
        path = item.get("path")
        if isinstance(path, str) and artifact_path_is_unsafe(path):
            raise NormalizationError(
                "normalized dataset artifact paths must be relative",
                code=NormalizationErrorCode.CATALOG_INVALID,
            )
    blob = {
        "artifacts": [dict(item) for item in entry.artifacts],
        "request": dict(entry.request),
        "report_summary": dict(entry.report_summary),
        "notes": entry.notes or "",
    }
    if manifest_contains_secrets(blob):
        raise NormalizationError(
            "catalog metadata must not contain secrets",
            code=NormalizationErrorCode.SECRET_LIKE_VALUE,
        )
    language = _catalog_language_blob(entry)
    if _has_forbidden_metric(language):
        raise NormalizationError(
            "catalog metadata must not contain forbidden metric language",
            code=NormalizationErrorCode.CATALOG_INVALID,
        )
    for stamp in (entry.as_of, entry.start_time, entry.end_time, entry.created_at):
        if stamp.tzinfo is None:
            raise NormalizationError(
                "catalog timestamps must be timezone-aware UTC",
                code=NormalizationErrorCode.NAIVE_TIMESTAMP,
            )


def register_normalized_dataset(
    session: Session,
    manifest_or_registration: (
        NormalizedDatasetCatalogEntry
        | NormalizedDatasetRegistration
        | NormalizationManifest
    ),
) -> NormalizedDatasetRegistration:
    """Upsert catalog metadata by id. Unique on ``manifest_hash``. No OHLCV rows."""
    if isinstance(manifest_or_registration, NormalizationManifest):
        raise NormalizationError(
            "register from a catalog entry or registration, "
            "not a bare artifact manifest",
            code=NormalizationErrorCode.CATALOG_INVALID,
        )
    entry = (
        manifest_or_registration.entry
        if isinstance(manifest_or_registration, NormalizedDatasetRegistration)
        else manifest_or_registration
    )
    validate_normalized_dataset_entry(entry)
    catalog_id = entry.normalized_dataset_id.strip()
    other = get_normalized_dataset_by_manifest_hash(session, entry.manifest_hash)
    if other is not None and other.normalized_dataset_id != catalog_id:
        raise NormalizationError(
            "manifest_hash already registered under a different normalized_dataset_id",
            code=NormalizationErrorCode.CATALOG_CONFLICT,
        )
    existing = session.scalars(
        select(NormalizedDatasetRecord).where(
            NormalizedDatasetRecord.normalized_dataset_id == catalog_id
        )
    ).first()
    payload = _record_payload(entry)
    if existing is None:
        row = NormalizedDatasetRecord(**cast(dict[str, Any], payload))
        session.add(row)
        session.flush()
        return NormalizedDatasetRegistration(
            entry=_entry_from_record(row), action="insert"
        )
    _apply_payload(existing, payload)
    session.flush()
    return NormalizedDatasetRegistration(
        entry=_entry_from_record(existing), action="update"
    )


def get_normalized_dataset_by_id(
    session: Session, normalized_dataset_id: str
) -> NormalizedDatasetCatalogEntry | None:
    stmt = select(NormalizedDatasetRecord).where(
        NormalizedDatasetRecord.normalized_dataset_id == normalized_dataset_id.strip()
    )
    row = session.scalars(stmt).first()
    if row is None:
        return None
    return _entry_from_record(row)


def get_normalized_dataset_by_manifest_hash(
    session: Session, manifest_hash: str
) -> NormalizedDatasetCatalogEntry | None:
    stmt = select(NormalizedDatasetRecord).where(
        NormalizedDatasetRecord.manifest_hash == manifest_hash.strip()
    )
    row = session.scalars(stmt).first()
    if row is None:
        return None
    return _entry_from_record(row)


def list_normalized_datasets(
    session: Session,
    filters: NormalizedDatasetCatalogFilters | None = None,
) -> tuple[NormalizedDatasetCatalogEntry, ...]:
    query = filters or build_normalized_dataset_catalog_filters()
    stmt = select(NormalizedDatasetRecord)
    if query.dataset_hash is not None:
        stmt = stmt.where(NormalizedDatasetRecord.dataset_hash == query.dataset_hash)
    if query.raw_dataset_hash is not None:
        stmt = stmt.where(
            NormalizedDatasetRecord.raw_dataset_hash == query.raw_dataset_hash
        )
    if query.adjustment_mode is not None:
        stmt = stmt.where(
            NormalizedDatasetRecord.adjustment_mode == query.adjustment_mode
        )
    if query.source_snapshot_id is not None:
        stmt = stmt.where(
            NormalizedDatasetRecord.source_snapshot_id == query.source_snapshot_id
        )
    if query.source_replay_id is not None:
        stmt = stmt.where(
            NormalizedDatasetRecord.source_replay_id == query.source_replay_id
        )
    if query.usable_only:
        stmt = stmt.where(NormalizedDatasetRecord.is_usable.is_(True))
    stmt = stmt.order_by(
        NormalizedDatasetRecord.created_at.desc(),
        NormalizedDatasetRecord.normalized_dataset_id.asc(),
    )
    return tuple(_entry_from_record(row) for row in session.scalars(stmt))


def compare_normalized_datasets(
    left: NormalizedDatasetCatalogEntry,
    right: NormalizedDatasetCatalogEntry,
) -> NormalizedDatasetComparison:
    """Compare two catalog rows. Does not read local files or compute returns."""
    differences: list[str] = []
    if left.dataset_hash != right.dataset_hash:
        differences.append("dataset_hash")
    if left.raw_dataset_hash != right.raw_dataset_hash:
        differences.append("raw_dataset_hash")
    if left.adjustment_mode != right.adjustment_mode:
        differences.append("adjustment_mode")
    if left.as_of != right.as_of:
        differences.append("as_of")
    if left.bar_count != right.bar_count:
        differences.append("bar_count")
    if left.adjusted_bar_count != right.adjusted_bar_count:
        differences.append("adjusted_bar_count")
    if left.applied_action_count != right.applied_action_count:
        differences.append("applied_action_count")
    if left.warning_count != right.warning_count:
        differences.append("warning_count")
    if left.error_count != right.error_count:
        differences.append("error_count")
    left_paths = _artifact_paths(left.artifacts)
    right_paths = _artifact_paths(right.artifacts)
    if left_paths != right_paths:
        differences.append("artifacts")
    if left.manifest_hash != right.manifest_hash:
        differences.append("manifest_hash")
    if left.manifest_hash == right.manifest_hash:
        verdict = COMPARISON_IDENTICAL
    elif left.dataset_hash == right.dataset_hash:
        verdict = COMPARISON_SAME_DATASET
    else:
        verdict = COMPARISON_DIFFERENT
    return NormalizedDatasetComparison(
        left_id=left.normalized_dataset_id,
        right_id=right.normalized_dataset_id,
        verdict=verdict,
        same_dataset_hash=left.dataset_hash == right.dataset_hash,
        same_raw_dataset_hash=left.raw_dataset_hash == right.raw_dataset_hash,
        same_adjustment_mode=left.adjustment_mode == right.adjustment_mode,
        same_as_of=left.as_of == right.as_of,
        same_bar_count=left.bar_count == right.bar_count,
        same_adjusted_bar_count=left.adjusted_bar_count == right.adjusted_bar_count,
        same_applied_action_count=left.applied_action_count
        == right.applied_action_count,
        same_warning_count=left.warning_count == right.warning_count,
        same_error_count=left.error_count == right.error_count,
        same_artifacts=left_paths == right_paths,
        same_manifest_hash=left.manifest_hash == right.manifest_hash,
        differences=tuple(differences),
    )


def compare_catalog_normalized_datasets(
    session: Session, left_id: str, right_id: str
) -> NormalizedDatasetComparison:
    left = get_normalized_dataset_by_id(session, left_id)
    right = get_normalized_dataset_by_id(session, right_id)
    if left is None or right is None:
        raise NormalizationError(
            "both normalized_dataset_id values must exist in the catalog",
            code=NormalizationErrorCode.CATALOG_MISSING,
        )
    return compare_normalized_datasets(left, right)


def normalized_dataset_is_reproducible(entry: NormalizedDatasetCatalogEntry) -> bool:
    """True when catalog metadata hashes, paths, and counts are valid."""
    try:
        validate_normalized_dataset_entry(entry)
    except NormalizationError:
        return False
    return True


def normalized_dataset_is_usable(entry: NormalizedDatasetCatalogEntry) -> bool:
    """True when the row is reproducible and has zero normalization errors."""
    return normalized_dataset_is_reproducible(entry) and entry.error_count == 0


def evaluate_normalized_dataset_usability(
    session: Session,
    normalized_dataset_id: str,
    base_dir: Path | str | None = None,
) -> NormalizedDatasetUsabilityReport:
    """Re-check catalog metadata against local artifacts. Does not repair files."""
    entry = get_normalized_dataset_by_id(session, normalized_dataset_id)
    if entry is None:
        return _finish_usability(
            normalized_dataset_id=normalized_dataset_id.strip(),
            dataset_hash=None,
            raw_dataset_hash=None,
            run_root=None,
            issues=(
                _usability_issue(
                    NormalizedDatasetUsabilitySeverity.ERROR,
                    NormalizedDatasetUsabilityCode.MISSING_CATALOG_ROW,
                    "normalized dataset is not registered",
                ),
            ),
            reproducible=False,
        )
    return evaluate_normalized_dataset_entry_usability(entry, base_dir)


def evaluate_normalized_dataset_entry_usability(
    entry: NormalizedDatasetCatalogEntry,
    base_dir: Path | str | None = None,
) -> NormalizedDatasetUsabilityReport:
    """Evaluate a catalog row against local artifacts. No PostgreSQL writes."""
    issues: list[NormalizedDatasetUsabilityIssue] = []
    try:
        validate_normalized_dataset_entry(entry)
        reproducible = True
    except NormalizationError as exc:
        reproducible = False
        issues.append(
            _usability_issue(
                NormalizedDatasetUsabilitySeverity.ERROR,
                _usability_code_for_error(exc),
                redact_secret_text(str(exc)),
            )
        )
    if entry.error_count:
        issues.append(
            _usability_issue(
                NormalizedDatasetUsabilitySeverity.ERROR,
                NormalizedDatasetUsabilityCode.CATALOG_ERRORS,
                "catalog row has normalization errors",
            )
        )
    run_root = _resolve_run_root(base_dir, entry.normalized_dataset_id)
    if run_root is None:
        issues.append(
            _usability_issue(
                NormalizedDatasetUsabilitySeverity.ERROR,
                NormalizedDatasetUsabilityCode.MISSING_ARTIFACT,
                "normalized dataset artifact directory is missing",
            )
        )
        return _finish_usability(
            normalized_dataset_id=entry.normalized_dataset_id,
            dataset_hash=entry.dataset_hash,
            raw_dataset_hash=entry.raw_dataset_hash,
            run_root=None if base_dir is None else Path(base_dir).name,
            issues=issues,
            reproducible=reproducible,
        )
    integrity = verify_normalization_artifacts(run_root)
    if not integrity.ok:
        integrity_codes = {item.code for item in integrity.issues}
        if integrity_codes & _MISSING_INTEGRITY_CODES:
            code = NormalizedDatasetUsabilityCode.MISSING_ARTIFACT
            message = "normalized dataset artifacts are missing"
        elif NormalizationIntegrityCode.INVALID_HASH.value in integrity_codes:
            code = NormalizedDatasetUsabilityCode.INVALID_HASH
            message = "normalized dataset artifacts have an invalid hash"
        elif NormalizationIntegrityCode.HASH_MISMATCH.value in integrity_codes:
            code = NormalizedDatasetUsabilityCode.HASH_MISMATCH
            message = "normalized dataset artifacts do not match declared hashes"
        else:
            code = NormalizedDatasetUsabilityCode.INTEGRITY_FAILED
            message = "normalized dataset artifacts failed verification"
        issues.append(
            _usability_issue(
                NormalizedDatasetUsabilitySeverity.ERROR,
                code,
                message,
            )
        )
    if integrity.dataset_hash and integrity.dataset_hash != entry.dataset_hash:
        issues.append(
            _usability_issue(
                NormalizedDatasetUsabilitySeverity.ERROR,
                NormalizedDatasetUsabilityCode.HASH_MISMATCH,
                "catalog dataset_hash does not match local artifacts",
            )
        )
    if (
        entry.raw_dataset_hash
        and integrity.raw_dataset_hash
        and integrity.raw_dataset_hash != entry.raw_dataset_hash
    ):
        issues.append(
            _usability_issue(
                NormalizedDatasetUsabilitySeverity.ERROR,
                NormalizedDatasetUsabilityCode.HASH_MISMATCH,
                "catalog raw_dataset_hash does not match local artifacts",
            )
        )
    return _finish_usability(
        normalized_dataset_id=entry.normalized_dataset_id,
        dataset_hash=entry.dataset_hash,
        raw_dataset_hash=entry.raw_dataset_hash,
        run_root=run_root.name,
        issues=issues,
        reproducible=reproducible and integrity.ok,
    )


def _resolve_run_root(
    base_dir: Path | str | None, normalized_dataset_id: str
) -> Path | None:
    if base_dir is None:
        return None
    root = Path(base_dir)
    if (root / MANIFEST_ARTIFACT_NAME).is_file():
        return root
    nested = root / normalized_dataset_id
    if (nested / MANIFEST_ARTIFACT_NAME).is_file():
        return nested
    if root.is_dir():
        return root
    return None


def _finish_usability(
    *,
    normalized_dataset_id: str,
    dataset_hash: str | None,
    raw_dataset_hash: str | None,
    run_root: str | None,
    issues: Sequence[NormalizedDatasetUsabilityIssue],
    reproducible: bool,
) -> NormalizedDatasetUsabilityReport:
    errors = sum(
        1
        for item in issues
        if item.severity == NormalizedDatasetUsabilitySeverity.ERROR.value
    )
    warnings = sum(
        1
        for item in issues
        if item.severity == NormalizedDatasetUsabilitySeverity.WARNING.value
    )
    ok = errors == 0
    return NormalizedDatasetUsabilityReport(
        ok=ok,
        usable=ok and reproducible,
        reproducible=reproducible and ok,
        normalized_dataset_id=normalized_dataset_id,
        dataset_hash=dataset_hash,
        raw_dataset_hash=raw_dataset_hash,
        run_root=run_root,
        error_count=errors,
        warning_count=warnings,
        issues=tuple(issues),
    )


def _usability_issue(
    severity: NormalizedDatasetUsabilitySeverity,
    code: NormalizedDatasetUsabilityCode,
    message: str,
) -> NormalizedDatasetUsabilityIssue:
    return NormalizedDatasetUsabilityIssue(
        severity=severity.value,
        code=code.value,
        message=redact_secret_text(message),
    )


def _usability_code_for_error(
    exc: NormalizationError,
) -> NormalizedDatasetUsabilityCode:
    if exc.code == NormalizationErrorCode.SECRET_LIKE_VALUE:
        return NormalizedDatasetUsabilityCode.SECRET_LIKE_VALUE
    text = str(exc).lower()
    if "hash" in text or "sha256" in text:
        return NormalizedDatasetUsabilityCode.INVALID_HASH
    if "relative" in text or "path" in text:
        return NormalizedDatasetUsabilityCode.ABSOLUTE_PATH
    if "forbidden" in text:
        return NormalizedDatasetUsabilityCode.FORBIDDEN_METRIC
    return NormalizedDatasetUsabilityCode.INTEGRITY_FAILED


def _catalog_language_blob(entry: NormalizedDatasetCatalogEntry) -> str:
    return " ".join(
        (
            entry.notes or "",
            canonical_json(dict(entry.request)),
            canonical_json(dict(entry.report_summary)),
        )
    )


def _has_forbidden_metric(blob: str) -> bool:
    lowered = blob.lower()
    return any(token in lowered for token in _FORBIDDEN_METRIC_TOKENS)


def _resolve_id(
    raw: str | None,
    *,
    deterministic: bool,
    dataset_hash: str,
    adjustment_mode: str,
    as_of: datetime,
) -> str:
    if raw is not None and raw.strip():
        return raw.strip()
    if deterministic:
        return deterministic_normalized_dataset_id(
            dataset_hash=dataset_hash,
            adjustment_mode=adjustment_mode,
            as_of=as_of,
        )
    return str(uuid4())


def _resolve_source_type(
    raw: str | None,
    *,
    source_snapshot_id: str | None,
    source_replay_id: str | None,
) -> str:
    if raw is not None and raw.strip():
        cleaned = raw.strip()
        if cleaned not in ALLOWED_SOURCE_TYPES:
            raise NormalizationError(
                "source_type is not a catalog source",
                code=NormalizationErrorCode.CATALOG_INVALID,
            )
        return cleaned
    if source_snapshot_id:
        return SOURCE_SNAPSHOT
    if source_replay_id:
        return SOURCE_REPLAY
    return SOURCE_LOCAL_ARTIFACTS


def _request_mapping(dataset: NormalizedDailyBarsDataset) -> dict[str, object]:
    request = dataset.request
    return {
        "as_of": canonical_datetime(request.as_of),
        "start_time": canonical_datetime(request.start_time),
        "end_time": canonical_datetime(request.end_time),
        "source_name": request.source_name,
        "adjustment_mode": request.adjustment_mode.value,
        "symbols": list(request.symbols) if request.symbols is not None else None,
    }


def _report_summary(
    dataset: NormalizedDailyBarsDataset, manifest: NormalizationManifest
) -> dict[str, object]:
    return {
        "ok": dataset.report.ok,
        "dataset_hash": dataset.dataset_hash,
        "raw_dataset_hash": dataset.raw_dataset_hash,
        "bar_count": dataset.report.bar_count,
        "applied_action_count": dataset.report.applied_action_count,
        "issue_count": dataset.report.issue_count,
        "warning_count": dataset.report.warning_count,
        "error_count": dataset.report.error_count,
        "issue_codes": sorted({item.code for item in dataset.report.issues}),
        "adjustment_mode": manifest.adjustment_mode,
    }


def _symbol_count(dataset: NormalizedDailyBarsDataset) -> int:
    if dataset.request.symbols:
        return len(dataset.request.symbols)
    return len({row.symbol for row in dataset.rows})


def _adjusted_bar_count(rows: Sequence[NormalizedDailyBar]) -> int:
    return sum(
        1
        for row in rows
        if row.price_factor != _ONE
        or row.volume_factor != _ONE
        or bool(row.applied_action_ids)
    )


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _artifact_paths(artifacts: Sequence[Mapping[str, object]]) -> tuple[str, ...]:
    paths: list[str] = []
    for item in artifacts:
        path = item.get("path")
        if isinstance(path, str):
            paths.append(path)
    return tuple(sorted(paths))


def _record_payload(entry: NormalizedDatasetCatalogEntry) -> dict[str, object]:
    return {
        "normalized_dataset_id": entry.normalized_dataset_id,
        "dataset_hash": entry.dataset_hash,
        "raw_dataset_hash": entry.raw_dataset_hash,
        "source_type": entry.source_type,
        "source_snapshot_id": entry.source_snapshot_id,
        "source_replay_id": entry.source_replay_id,
        "adjustment_mode": entry.adjustment_mode,
        "as_of": entry.as_of,
        "start_time": entry.start_time,
        "end_time": entry.end_time,
        "symbol_count": entry.symbol_count,
        "bar_count": entry.bar_count,
        "adjusted_bar_count": entry.adjusted_bar_count,
        "applied_action_count": entry.applied_action_count,
        "warning_count": entry.warning_count,
        "error_count": entry.error_count,
        "is_reproducible": entry.is_reproducible,
        "is_usable": entry.is_usable,
        "artifacts": [dict(item) for item in entry.artifacts],
        "request": dict(entry.request),
        "report_summary": dict(entry.report_summary),
        "manifest_hash": entry.manifest_hash,
        "package_version": entry.package_version,
        "git_commit": entry.git_commit,
        "created_at": entry.created_at,
        "notes": entry.notes,
    }


def _apply_payload(row: NormalizedDatasetRecord, payload: Mapping[str, object]) -> None:
    row.dataset_hash = str(payload["dataset_hash"])
    raw_hash = payload["raw_dataset_hash"]
    row.raw_dataset_hash = str(raw_hash) if raw_hash is not None else None
    row.source_type = str(payload["source_type"])
    snapshot_id = payload["source_snapshot_id"]
    row.source_snapshot_id = str(snapshot_id) if snapshot_id is not None else None
    replay_id = payload["source_replay_id"]
    row.source_replay_id = str(replay_id) if replay_id is not None else None
    row.adjustment_mode = str(payload["adjustment_mode"])
    as_of = payload["as_of"]
    start_time = payload["start_time"]
    end_time = payload["end_time"]
    created_at = payload["created_at"]
    if not isinstance(as_of, datetime) or not isinstance(start_time, datetime):
        raise NormalizationError(
            "as_of and start_time must be datetimes",
            code=NormalizationErrorCode.CATALOG_INVALID,
        )
    if not isinstance(end_time, datetime) or not isinstance(created_at, datetime):
        raise NormalizationError(
            "end_time and created_at must be datetimes",
            code=NormalizationErrorCode.CATALOG_INVALID,
        )
    row.as_of = as_of
    row.start_time = start_time
    row.end_time = end_time
    row.created_at = created_at
    row.symbol_count = _as_int(payload["symbol_count"], field="symbol_count")
    row.bar_count = _as_int(payload["bar_count"], field="bar_count")
    row.adjusted_bar_count = _as_int(
        payload["adjusted_bar_count"], field="adjusted_bar_count"
    )
    row.applied_action_count = _as_int(
        payload["applied_action_count"], field="applied_action_count"
    )
    row.warning_count = _as_int(payload["warning_count"], field="warning_count")
    row.error_count = _as_int(payload["error_count"], field="error_count")
    row.is_reproducible = bool(payload["is_reproducible"])
    row.is_usable = bool(payload["is_usable"])
    artifacts = payload["artifacts"]
    request = payload["request"]
    report_summary = payload["report_summary"]
    if not isinstance(artifacts, list) or not isinstance(request, dict):
        raise NormalizationError(
            "artifacts must be a list and request must be an object",
            code=NormalizationErrorCode.CATALOG_INVALID,
        )
    if not isinstance(report_summary, dict):
        raise NormalizationError(
            "report_summary must be an object",
            code=NormalizationErrorCode.CATALOG_INVALID,
        )
    row.artifacts = [dict(item) for item in artifacts if isinstance(item, dict)]
    row.request = dict(request)
    row.report_summary = dict(report_summary)
    row.manifest_hash = str(payload["manifest_hash"])
    row.package_version = str(payload["package_version"])
    git_commit = payload["git_commit"]
    row.git_commit = str(git_commit) if git_commit is not None else None
    notes = payload["notes"]
    row.notes = str(notes) if notes is not None else None


def _as_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise NormalizationError(
            f"{field} must be an integer",
            code=NormalizationErrorCode.CATALOG_INVALID,
        )
    return value


def _entry_from_record(row: NormalizedDatasetRecord) -> NormalizedDatasetCatalogEntry:
    return NormalizedDatasetCatalogEntry(
        normalized_dataset_id=row.normalized_dataset_id,
        dataset_hash=row.dataset_hash,
        raw_dataset_hash=row.raw_dataset_hash,
        source_type=row.source_type,
        source_snapshot_id=row.source_snapshot_id,
        source_replay_id=row.source_replay_id,
        adjustment_mode=row.adjustment_mode,
        as_of=row.as_of,
        start_time=row.start_time,
        end_time=row.end_time,
        symbol_count=row.symbol_count,
        bar_count=row.bar_count,
        adjusted_bar_count=row.adjusted_bar_count,
        applied_action_count=row.applied_action_count,
        warning_count=row.warning_count,
        error_count=row.error_count,
        is_reproducible=row.is_reproducible,
        is_usable=row.is_usable,
        artifacts=tuple(dict(item) for item in row.artifacts),
        request=dict(row.request),
        report_summary=dict(row.report_summary),
        manifest_hash=row.manifest_hash,
        package_version=row.package_version,
        git_commit=row.git_commit,
        created_at=row.created_at,
        registered_at=row.registered_at,
        notes=row.notes,
    )
