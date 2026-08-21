"""Local read-only snapshot artifact and catalog integrity checks."""

from __future__ import annotations

import csv
import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session

from quant_platform.research.catalog import (
    get_dataset_snapshot_by_id,
    list_dataset_snapshots,
)
from quant_platform.research.catalog_types import (
    DatasetSnapshotCatalogEntry,
    DatasetSnapshotCatalogFilters,
    build_dataset_snapshot_catalog_filters,
)
from quant_platform.research.errors import DatasetErrorCode, DatasetValidationError
from quant_platform.research.integrity_types import (
    SEVERITY_RANK,
    ArtifactVerificationIssue,
    ArtifactVerificationReport,
    ArtifactVerificationRequest,
    CatalogIntegrityReport,
    IntegrityIssueCode,
    IntegritySeverity,
    SnapshotArtifactStatus,
)
from quant_platform.research.snapshot_types import (
    DAILY_BARS_ARTIFACT_NAME,
    MANIFEST_ARTIFACT_NAME,
    QUALITY_ARTIFACT_NAME,
)
from quant_platform.research.snapshots import (
    hash_daily_bars_dataset,
    hash_manifest_mapping,
    hash_quality_mapping,
    is_sha256_digest,
    manifest_contains_secrets,
)
from quant_platform.research.types import DAILY_BAR_DATASET_COLUMNS, DailyBarDatasetRow

_CATALOG_COMPARE_FIELDS: tuple[str, ...] = (
    "content_hash",
    "quality_hash",
    "manifest_hash",
    "row_count",
    "instrument_count",
    "error_count",
    "warning_count",
    "package_version",
    "git_commit",
)


def verify_snapshot_artifacts(
    snapshot_root: Path | str | ArtifactVerificationRequest,
    *,
    expected_snapshot_id: str | None = None,
) -> ArtifactVerificationReport:
    """Verify a local snapshot folder. Does not write files or touch PostgreSQL."""
    request = _as_request(snapshot_root, expected_snapshot_id=expected_snapshot_id)
    root = Path(request.snapshot_root).expanduser()
    issues: list[ArtifactVerificationIssue] = []
    statuses: list[SnapshotArtifactStatus] = []
    if not root.exists() or not root.is_dir():
        issues.append(
            _issue(
                IntegritySeverity.ERROR,
                IntegrityIssueCode.MISSING_SNAPSHOT_DIR,
                "snapshot directory is missing",
                path=str(root),
            )
        )
        return _finish_report(
            root=root,
            snapshot_id=request.expected_snapshot_id,
            issues=issues,
            artifacts=(),
        )

    resolved_root = root.resolve()
    manifest_path = resolved_root / MANIFEST_ARTIFACT_NAME
    if not manifest_path.is_file():
        issues.append(
            _issue(
                IntegritySeverity.ERROR,
                IntegrityIssueCode.MISSING_MANIFEST,
                "manifest.json is missing",
                path=MANIFEST_ARTIFACT_NAME,
            )
        )
        return _finish_report(
            root=root,
            snapshot_id=request.expected_snapshot_id,
            issues=issues,
            artifacts=(),
        )

    manifest_text = manifest_path.read_text(encoding="utf-8")
    if manifest_contains_secrets(manifest_text):
        issues.append(
            _issue(
                IntegritySeverity.ERROR,
                IntegrityIssueCode.SECRET_LIKE_VALUE,
                "manifest contains a secret-like marker",
                path=MANIFEST_ARTIFACT_NAME,
            )
        )
    try:
        loaded = json.loads(manifest_text)
    except json.JSONDecodeError:
        issues.append(
            _issue(
                IntegritySeverity.ERROR,
                IntegrityIssueCode.INVALID_JSON,
                "manifest.json is not valid JSON",
                path=MANIFEST_ARTIFACT_NAME,
            )
        )
        return _finish_report(
            root=root,
            snapshot_id=request.expected_snapshot_id,
            issues=issues,
            artifacts=(),
        )
    if not isinstance(loaded, dict):
        issues.append(
            _issue(
                IntegritySeverity.ERROR,
                IntegrityIssueCode.INVALID_JSON,
                "manifest.json must be an object",
                path=MANIFEST_ARTIFACT_NAME,
            )
        )
        return _finish_report(
            root=root,
            snapshot_id=request.expected_snapshot_id,
            issues=issues,
            artifacts=(),
        )
    manifest = dict(loaded)
    snapshot_id = _optional_str(manifest.get("snapshot_id"))
    if (
        request.expected_snapshot_id is not None
        and snapshot_id is not None
        and snapshot_id != request.expected_snapshot_id
    ):
        issues.append(
            _issue(
                IntegritySeverity.ERROR,
                IntegrityIssueCode.CATALOG_MANIFEST_MISMATCH,
                "manifest snapshot_id does not match the requested id",
                expected=request.expected_snapshot_id,
                actual=snapshot_id,
            )
        )

    stored_manifest_hash = _optional_str(manifest.get("manifest_hash"))
    stored_content_hash = _optional_str(manifest.get("content_hash"))
    stored_quality_hash = _optional_str(manifest.get("quality_hash"))
    _check_hash_field(issues, "manifest_hash", stored_manifest_hash)
    _check_hash_field(issues, "content_hash", stored_content_hash)
    _check_hash_field(issues, "quality_hash", stored_quality_hash)

    recomputed_manifest_hash = hash_manifest_mapping(manifest)
    if stored_manifest_hash is not None and is_sha256_digest(stored_manifest_hash):
        if recomputed_manifest_hash != stored_manifest_hash:
            issues.append(
                _issue(
                    IntegritySeverity.ERROR,
                    IntegrityIssueCode.MANIFEST_HASH_MISMATCH,
                    "recomputed manifest_hash does not match the stored digest",
                    path=MANIFEST_ARTIFACT_NAME,
                    expected=stored_manifest_hash,
                    actual=recomputed_manifest_hash,
                )
            )

    artifacts_raw = manifest.get("artifacts")
    artifact_specs = _artifact_specs(artifacts_raw, issues)
    csv_row_count: int | None = None
    csv_instrument_count: int | None = None
    recomputed_content_hash: str | None = None
    recomputed_quality_hash: str | None = None
    for spec in artifact_specs:
        status, artifact_issues, extra = _verify_one_artifact(resolved_root, spec)
        statuses.append(status)
        issues.extend(artifact_issues)
        csv_count = _extra_int(extra, "csv_row_count")
        if csv_count is not None:
            csv_row_count = csv_count
            csv_instrument_count = _extra_int(extra, "csv_instrument_count")
            recomputed_content_hash = _extra_str(extra, "content_hash")
        quality_recomputed = _extra_str(extra, "quality_hash")
        if quality_recomputed is not None:
            recomputed_quality_hash = quality_recomputed

    row_count = _optional_int(manifest.get("row_count"))
    instrument_count = _optional_int(manifest.get("instrument_count"))
    if (
        row_count is not None
        and csv_row_count is not None
        and row_count != csv_row_count
    ):
        issues.append(
            _issue(
                IntegritySeverity.ERROR,
                IntegrityIssueCode.ROW_COUNT_MISMATCH,
                "CSV row count does not match manifest.row_count",
                path=DAILY_BARS_ARTIFACT_NAME,
                expected=str(row_count),
                actual=str(csv_row_count),
            )
        )
    if (
        instrument_count is not None
        and csv_instrument_count is not None
        and instrument_count != csv_instrument_count
    ):
        issues.append(
            _issue(
                IntegritySeverity.ERROR,
                IntegrityIssueCode.INSTRUMENT_COUNT_MISMATCH,
                "CSV instrument count does not match manifest.instrument_count",
                path=DAILY_BARS_ARTIFACT_NAME,
                expected=str(instrument_count),
                actual=str(csv_instrument_count),
            )
        )
    if (
        stored_content_hash is not None
        and is_sha256_digest(stored_content_hash)
        and recomputed_content_hash is not None
        and recomputed_content_hash != stored_content_hash
    ):
        issues.append(
            _issue(
                IntegritySeverity.ERROR,
                IntegrityIssueCode.CONTENT_HASH_MISMATCH,
                "recomputed content_hash does not match the stored digest",
                path=DAILY_BARS_ARTIFACT_NAME,
                expected=stored_content_hash,
                actual=recomputed_content_hash,
            )
        )
    if (
        stored_quality_hash is not None
        and is_sha256_digest(stored_quality_hash)
        and recomputed_quality_hash is not None
        and recomputed_quality_hash != stored_quality_hash
    ):
        issues.append(
            _issue(
                IntegritySeverity.ERROR,
                IntegrityIssueCode.QUALITY_HASH_MISMATCH,
                "recomputed quality_hash does not match the stored digest",
                path=QUALITY_ARTIFACT_NAME,
                expected=stored_quality_hash,
                actual=recomputed_quality_hash,
            )
        )
    return _finish_report(
        root=root,
        snapshot_id=snapshot_id or request.expected_snapshot_id,
        issues=issues,
        artifacts=tuple(statuses),
        content_hash=stored_content_hash,
        recomputed_content_hash=recomputed_content_hash,
        quality_hash=stored_quality_hash,
        recomputed_quality_hash=recomputed_quality_hash,
        manifest_hash=stored_manifest_hash,
        recomputed_manifest_hash=recomputed_manifest_hash,
        row_count=row_count,
        csv_row_count=csv_row_count,
        instrument_count=instrument_count,
        csv_instrument_count=csv_instrument_count,
    )


def verify_catalog_entry_artifacts(
    session: Session,
    snapshot_id: str,
    base_dir: Path | str,
) -> ArtifactVerificationReport:
    """Verify one catalog row against a local snapshot folder. Read-only."""
    entry = get_dataset_snapshot_by_id(session, snapshot_id)
    root = Path(base_dir).expanduser()
    if entry is None:
        return _finish_report(
            root=root,
            snapshot_id=snapshot_id,
            issues=[
                _issue(
                    IntegritySeverity.ERROR,
                    IntegrityIssueCode.CATALOG_ENTRY_MISSING,
                    "snapshot_id is not in the catalog",
                    expected=snapshot_id,
                )
            ],
            artifacts=(),
        )
    resolved = resolve_snapshot_directory(root, snapshot_id)
    if resolved is None:
        return _finish_report(
            root=root,
            snapshot_id=snapshot_id,
            issues=[
                _issue(
                    IntegritySeverity.ERROR,
                    IntegrityIssueCode.MISSING_SNAPSHOT_DIR,
                    "no local snapshot folder matched this snapshot_id",
                    path=str(root),
                    expected=snapshot_id,
                )
            ],
            artifacts=(),
        )
    report = verify_snapshot_artifacts(resolved, expected_snapshot_id=snapshot_id)
    extra = _catalog_mismatch_issues(entry, resolved)
    return _merge_issues(report, extra)


def verify_catalog(
    session: Session,
    base_dir: Path | str,
    filters: DatasetSnapshotCatalogFilters | None = None,
    *,
    snapshot_id: str | None = None,
    usable_only: bool = False,
) -> CatalogIntegrityReport:
    """Verify catalog rows against local folders under ``base_dir``. Read-only."""
    query = filters
    if query is None:
        query = build_dataset_snapshot_catalog_filters(
            snapshot_id=snapshot_id,
            usable_only=usable_only,
        )
    entries = list_dataset_snapshots(session, query)
    reports = tuple(
        verify_catalog_entry_artifacts(session, entry.snapshot_id, base_dir)
        for entry in entries
    )
    error_count = sum(item.error_count for item in reports)
    warning_count = sum(item.warning_count for item in reports)
    return CatalogIntegrityReport(
        base_dir=str(Path(base_dir)),
        entry_count=len(entries),
        verified_count=sum(1 for item in reports if item.ok),
        error_count=error_count,
        warning_count=warning_count,
        ok=error_count == 0,
        reports=reports,
    )


def resolve_snapshot_directory(base_dir: Path, snapshot_id: str) -> Path | None:
    """Find a snapshot folder for ``snapshot_id`` under ``base_dir``."""
    base = Path(base_dir).expanduser()
    if not base.exists():
        return None
    if base.is_file():
        return None
    direct = base / MANIFEST_ARTIFACT_NAME
    if direct.is_file() and _manifest_file_snapshot_id(direct) == snapshot_id:
        return base
    named = base / snapshot_id
    named_manifest = named / MANIFEST_ARTIFACT_NAME
    if (
        named_manifest.is_file()
        and _manifest_file_snapshot_id(named_manifest) == snapshot_id
    ):
        return named
    if not base.is_dir():
        return None
    matches: list[Path] = []
    for child in sorted(base.iterdir()):
        if not child.is_dir():
            continue
        manifest = child / MANIFEST_ARTIFACT_NAME
        if manifest.is_file() and _manifest_file_snapshot_id(manifest) == snapshot_id:
            matches.append(child)
    if len(matches) == 1:
        return matches[0]
    return None


def load_snapshot_daily_bar_rows(path: Path) -> tuple[DailyBarDatasetRow, ...]:
    """Parse a snapshot ``daily_bars.csv`` into dataset rows for hashing."""
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise DatasetValidationError(
                "daily_bars.csv has no header",
                code=DatasetErrorCode.CATALOG_INVALID,
            )
        missing = [
            name for name in DAILY_BAR_DATASET_COLUMNS if name not in reader.fieldnames
        ]
        if missing:
            raise DatasetValidationError(
                "daily_bars.csv is missing required columns",
                code=DatasetErrorCode.CATALOG_INVALID,
            )
        rows: list[DailyBarDatasetRow] = []
        for record in reader:
            rows.append(_row_from_csv(record))
    return tuple(rows)


def _as_request(
    snapshot_root: Path | str | ArtifactVerificationRequest,
    *,
    expected_snapshot_id: str | None,
) -> ArtifactVerificationRequest:
    if isinstance(snapshot_root, ArtifactVerificationRequest):
        requested = snapshot_root.expected_snapshot_id or expected_snapshot_id
        return ArtifactVerificationRequest(
            snapshot_root=snapshot_root.snapshot_root,
            expected_snapshot_id=requested,
        )
    return ArtifactVerificationRequest(
        snapshot_root=Path(snapshot_root),
        expected_snapshot_id=expected_snapshot_id,
    )


def _artifact_specs(
    raw: object, issues: list[ArtifactVerificationIssue]
) -> tuple[dict[str, str], ...]:
    defaults = (
        {"name": "daily_bars", "path": DAILY_BARS_ARTIFACT_NAME, "kind": "csv"},
        {"name": "quality_report", "path": QUALITY_ARTIFACT_NAME, "kind": "json"},
        {"name": "manifest", "path": MANIFEST_ARTIFACT_NAME, "kind": "json"},
    )
    if raw is None:
        return defaults
    if not isinstance(raw, list) or not raw:
        issues.append(
            _issue(
                IntegritySeverity.ERROR,
                IntegrityIssueCode.MISSING_ARTIFACT,
                "manifest artifacts list is empty",
                path=MANIFEST_ARTIFACT_NAME,
            )
        )
        return defaults
    specs: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            issues.append(
                _issue(
                    IntegritySeverity.ERROR,
                    IntegrityIssueCode.INVALID_JSON,
                    "each artifact must be an object",
                    path=MANIFEST_ARTIFACT_NAME,
                )
            )
            continue
        name = item.get("name")
        path = item.get("path")
        kind = item.get("kind")
        if (
            not isinstance(name, str)
            or not isinstance(path, str)
            or not isinstance(kind, str)
        ):
            issues.append(
                _issue(
                    IntegritySeverity.ERROR,
                    IntegrityIssueCode.INVALID_JSON,
                    "artifact name, path, and kind must be strings",
                    path=MANIFEST_ARTIFACT_NAME,
                )
            )
            continue
        specs.append({"name": name, "path": path, "kind": kind})
    return tuple(specs) if specs else defaults


def _verify_one_artifact(
    root: Path,
    spec: Mapping[str, str],
) -> tuple[SnapshotArtifactStatus, list[ArtifactVerificationIssue], dict[str, object]]:
    issues: list[ArtifactVerificationIssue] = []
    extra: dict[str, object] = {}
    raw_path = spec["path"]
    name = spec["name"]
    relative = True
    escaped = False
    exists = False
    if not raw_path.strip():
        relative = False
        issues.append(
            _issue(
                IntegritySeverity.ERROR,
                IntegrityIssueCode.EMPTY_ARTIFACT_PATH,
                "artifact path is empty",
                path=name,
            )
        )
        status = SnapshotArtifactStatus(
            name=name, path=raw_path, exists=False, relative=False, escaped=False
        )
        return status, issues, extra
    candidate = Path(raw_path)
    if candidate.is_absolute():
        relative = False
        issues.append(
            _issue(
                IntegritySeverity.ERROR,
                IntegrityIssueCode.ABSOLUTE_PATH,
                "artifact path must be relative",
                path=raw_path,
            )
        )
    if ".." in candidate.parts:
        escaped = True
        relative = False
        issues.append(
            _issue(
                IntegritySeverity.ERROR,
                IntegrityIssueCode.PATH_ESCAPE,
                "artifact path must not escape the snapshot directory",
                path=raw_path,
            )
        )
    if manifest_contains_secrets(raw_path) or manifest_contains_secrets(name):
        issues.append(
            _issue(
                IntegritySeverity.ERROR,
                IntegrityIssueCode.SECRET_LIKE_VALUE,
                "artifact name or path looks like a secret",
                path=name,
            )
        )
    target: Path | None = None
    if relative and not escaped:
        target = (root / candidate).resolve()
        if not target.is_relative_to(root):
            escaped = True
            relative = False
            issues.append(
                _issue(
                    IntegritySeverity.ERROR,
                    IntegrityIssueCode.PATH_ESCAPE,
                    "artifact path must not escape the snapshot directory",
                    path=raw_path,
                )
            )
            target = None
    if target is not None:
        exists = target.is_file()
        if not exists:
            issues.append(
                _issue(
                    IntegritySeverity.ERROR,
                    IntegrityIssueCode.MISSING_ARTIFACT,
                    "listed artifact file is missing",
                    path=raw_path,
                )
            )
        elif spec["kind"] == "csv" or raw_path == DAILY_BARS_ARTIFACT_NAME:
            extra.update(_hash_csv_artifact(target, issues, raw_path))
        elif spec["kind"] == "json" and raw_path == QUALITY_ARTIFACT_NAME:
            extra.update(_hash_quality_artifact(target, issues, raw_path))
    status = SnapshotArtifactStatus(
        name=name,
        path=raw_path,
        exists=exists,
        relative=relative,
        escaped=escaped,
    )
    return status, issues, extra


def _hash_csv_artifact(
    path: Path, issues: list[ArtifactVerificationIssue], relative: str
) -> dict[str, object]:
    try:
        rows = load_snapshot_daily_bar_rows(path)
    except (DatasetValidationError, OSError, ValueError, KeyError):
        issues.append(
            _issue(
                IntegritySeverity.ERROR,
                IntegrityIssueCode.INVALID_CSV,
                "daily_bars.csv could not be parsed as a snapshot CSV",
                path=relative,
            )
        )
        return {}
    return {
        "content_hash": hash_daily_bars_dataset(rows),
        "csv_row_count": len(rows),
        "csv_instrument_count": len({row.instrument_id for row in rows}),
    }


def _hash_quality_artifact(
    path: Path, issues: list[ArtifactVerificationIssue], relative: str
) -> dict[str, object]:
    try:
        text = path.read_text(encoding="utf-8")
        loaded = json.loads(text)
    except (OSError, json.JSONDecodeError):
        issues.append(
            _issue(
                IntegritySeverity.ERROR,
                IntegrityIssueCode.INVALID_JSON,
                "quality.json is not valid JSON",
                path=relative,
            )
        )
        return {}
    if not isinstance(loaded, dict):
        issues.append(
            _issue(
                IntegritySeverity.ERROR,
                IntegrityIssueCode.INVALID_JSON,
                "quality.json must be an object",
                path=relative,
            )
        )
        return {}
    if manifest_contains_secrets(text):
        issues.append(
            _issue(
                IntegritySeverity.ERROR,
                IntegrityIssueCode.SECRET_LIKE_VALUE,
                "quality.json contains a secret-like marker",
                path=relative,
            )
        )
    return {"quality_hash": hash_quality_mapping(loaded)}


def _catalog_mismatch_issues(
    entry: DatasetSnapshotCatalogEntry, snapshot_root: Path
) -> list[ArtifactVerificationIssue]:
    manifest_path = snapshot_root.resolve() / MANIFEST_ARTIFACT_NAME
    if not manifest_path.is_file():
        return []
    try:
        loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(loaded, dict):
        return []
    issues: list[ArtifactVerificationIssue] = []
    local_values: dict[str, object] = {
        "content_hash": loaded.get("content_hash"),
        "quality_hash": loaded.get("quality_hash"),
        "manifest_hash": loaded.get("manifest_hash"),
        "row_count": loaded.get("row_count"),
        "instrument_count": loaded.get("instrument_count"),
        "error_count": loaded.get("error_count"),
        "warning_count": loaded.get("warning_count"),
        "package_version": loaded.get("package_version"),
        "git_commit": loaded.get("git_commit"),
    }
    catalog_values: dict[str, object] = {
        "content_hash": entry.content_hash,
        "quality_hash": entry.quality_hash,
        "manifest_hash": entry.manifest_hash,
        "row_count": entry.row_count,
        "instrument_count": entry.instrument_count,
        "error_count": entry.error_count,
        "warning_count": entry.warning_count,
        "package_version": entry.package_version,
        "git_commit": entry.git_commit,
    }
    for field in _CATALOG_COMPARE_FIELDS:
        if local_values[field] != catalog_values[field]:
            issues.append(
                _issue(
                    IntegritySeverity.ERROR,
                    IntegrityIssueCode.CATALOG_MANIFEST_MISMATCH,
                    f"catalog {field} does not match the local manifest",
                    path=MANIFEST_ARTIFACT_NAME,
                    expected=str(catalog_values[field]),
                    actual=str(local_values[field]),
                )
            )
    catalog_paths = tuple(
        sorted(
            str(item.get("path"))
            for item in entry.artifacts
            if isinstance(item.get("path"), str)
        )
    )
    local_artifacts = loaded.get("artifacts")
    local_paths: tuple[str, ...] = ()
    if isinstance(local_artifacts, list):
        local_paths = tuple(
            sorted(
                str(item.get("path"))
                for item in local_artifacts
                if isinstance(item, dict) and isinstance(item.get("path"), str)
            )
        )
    if catalog_paths != local_paths:
        issues.append(
            _issue(
                IntegritySeverity.ERROR,
                IntegrityIssueCode.CATALOG_MANIFEST_MISMATCH,
                "catalog artifact paths do not match the local manifest",
                path=MANIFEST_ARTIFACT_NAME,
            )
        )
    return issues


def _merge_issues(
    report: ArtifactVerificationReport, extra: Sequence[ArtifactVerificationIssue]
) -> ArtifactVerificationReport:
    issues = _sorted_issues((*report.issues, *extra))
    error_count = sum(1 for item in issues if item.severity == IntegritySeverity.ERROR)
    warning_count = sum(
        1 for item in issues if item.severity == IntegritySeverity.WARNING
    )
    info_count = sum(1 for item in issues if item.severity == IntegritySeverity.INFO)
    return ArtifactVerificationReport(
        snapshot_root=report.snapshot_root,
        snapshot_id=report.snapshot_id,
        ok=error_count == 0,
        error_count=error_count,
        warning_count=warning_count,
        info_count=info_count,
        issues=issues,
        artifacts=report.artifacts,
        content_hash=report.content_hash,
        recomputed_content_hash=report.recomputed_content_hash,
        quality_hash=report.quality_hash,
        recomputed_quality_hash=report.recomputed_quality_hash,
        manifest_hash=report.manifest_hash,
        recomputed_manifest_hash=report.recomputed_manifest_hash,
        row_count=report.row_count,
        csv_row_count=report.csv_row_count,
        instrument_count=report.instrument_count,
        csv_instrument_count=report.csv_instrument_count,
    )


def _finish_report(
    *,
    root: Path,
    snapshot_id: str | None,
    issues: Sequence[ArtifactVerificationIssue],
    artifacts: tuple[SnapshotArtifactStatus, ...],
    content_hash: str | None = None,
    recomputed_content_hash: str | None = None,
    quality_hash: str | None = None,
    recomputed_quality_hash: str | None = None,
    manifest_hash: str | None = None,
    recomputed_manifest_hash: str | None = None,
    row_count: int | None = None,
    csv_row_count: int | None = None,
    instrument_count: int | None = None,
    csv_instrument_count: int | None = None,
) -> ArtifactVerificationReport:
    ordered = _sorted_issues(issues)
    error_count = sum(1 for item in ordered if item.severity == IntegritySeverity.ERROR)
    warning_count = sum(
        1 for item in ordered if item.severity == IntegritySeverity.WARNING
    )
    info_count = sum(1 for item in ordered if item.severity == IntegritySeverity.INFO)
    return ArtifactVerificationReport(
        snapshot_root=str(root),
        snapshot_id=snapshot_id,
        ok=error_count == 0,
        error_count=error_count,
        warning_count=warning_count,
        info_count=info_count,
        issues=ordered,
        artifacts=artifacts,
        content_hash=content_hash,
        recomputed_content_hash=recomputed_content_hash,
        quality_hash=quality_hash,
        recomputed_quality_hash=recomputed_quality_hash,
        manifest_hash=manifest_hash,
        recomputed_manifest_hash=recomputed_manifest_hash,
        row_count=row_count,
        csv_row_count=csv_row_count,
        instrument_count=instrument_count,
        csv_instrument_count=csv_instrument_count,
    )


def _sorted_issues(
    issues: Sequence[ArtifactVerificationIssue],
) -> tuple[ArtifactVerificationIssue, ...]:
    return tuple(
        sorted(
            issues,
            key=lambda item: (
                SEVERITY_RANK.get(item.severity, 9),
                item.code,
                item.path or "",
                item.message,
            ),
        )
    )


def _issue(
    severity: IntegritySeverity,
    code: IntegrityIssueCode,
    message: str,
    *,
    path: str | None = None,
    expected: str | None = None,
    actual: str | None = None,
) -> ArtifactVerificationIssue:
    return ArtifactVerificationIssue(
        severity=severity.value,
        code=code.value,
        message=message,
        path=_safe_text(path),
        expected=_safe_text(expected),
        actual=_safe_text(actual),
    )


def _safe_text(value: str | None) -> str | None:
    if value is None:
        return None
    if manifest_contains_secrets(value):
        return "[redacted]"
    return value


def _check_hash_field(
    issues: list[ArtifactVerificationIssue], field: str, value: str | None
) -> None:
    if value is None or not is_sha256_digest(value):
        issues.append(
            _issue(
                IntegritySeverity.ERROR,
                IntegrityIssueCode.INVALID_HASH,
                f"{field} must be a sha256:<64 hex> digest",
                path=MANIFEST_ARTIFACT_NAME,
                actual=value,
            )
        )


def _extra_int(extra: Mapping[str, object], key: str) -> int | None:
    value = extra.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _extra_str(extra: Mapping[str, object], key: str) -> str | None:
    value = extra.get(key)
    return value if isinstance(value, str) else None


def integrity_report_json(
    report: ArtifactVerificationReport | CatalogIntegrityReport,
) -> str:
    """Stable JSON for integrity reports (sorted keys, no secrets)."""
    return (
        json.dumps(report.as_mapping(), indent=2, sort_keys=True, ensure_ascii=True)
        + "\n"
    )


def _optional_str(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _manifest_file_snapshot_id(path: Path) -> str | None:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(loaded, dict):
        return None
    return _optional_str(loaded.get("snapshot_id"))


def _row_from_csv(record: Mapping[str, str | None]) -> DailyBarDatasetRow:
    volume_raw = (record.get("volume") or "").strip()
    correction_reason = (record.get("correction_reason") or "").strip() or None
    exchange = (record.get("exchange_code") or "").strip() or None
    currency = (record.get("currency") or "").strip() or None
    return DailyBarDatasetRow(
        instrument_id=UUID(_required(record, "instrument_id")),
        symbol=_required(record, "symbol"),
        exchange_code=exchange,
        asset_class=_required(record, "asset_class"),
        currency=currency,
        observation_time=_parse_csv_datetime(_required(record, "observation_time")),
        available_time=_parse_csv_datetime(_required(record, "available_time")),
        open=Decimal(_required(record, "open")),
        high=Decimal(_required(record, "high")),
        low=Decimal(_required(record, "low")),
        close=Decimal(_required(record, "close")),
        volume=Decimal(volume_raw) if volume_raw else None,
        source_name=_required(record, "source_name"),
        ingestion_run_id=UUID(_required(record, "ingestion_run_id")),
        is_correction=_parse_csv_bool(_required(record, "is_correction")),
        correction_reason=correction_reason,
    )


def _required(record: Mapping[str, str | None], field: str) -> str:
    value = record.get(field)
    if value is None or not str(value).strip():
        raise DatasetValidationError(
            f"daily_bars.csv missing {field}",
            code=DatasetErrorCode.CATALOG_INVALID,
        )
    return str(value).strip()


def _parse_csv_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise DatasetValidationError(
            "daily_bars.csv timestamps must be timezone-aware",
            code=DatasetErrorCode.NAIVE_TIMESTAMP,
        )
    return parsed


def _parse_csv_bool(value: str) -> bool:
    lowered = value.strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    raise DatasetValidationError(
        "daily_bars.csv is_correction must be true or false",
        code=DatasetErrorCode.CATALOG_INVALID,
    )
