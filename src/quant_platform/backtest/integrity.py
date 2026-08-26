"""Read-only integrity checks for local backtest artifacts. No writes."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from sqlalchemy.orm import Session

from quant_platform.backtest.catalog import (
    get_backtest_run_by_id,
    list_backtest_runs,
)
from quant_platform.backtest.errors import BacktestError
from quant_platform.backtest.integrity_types import (
    SEVERITY_RANK,
    BacktestArtifactStatus,
    BacktestArtifactVerificationIssue,
    BacktestArtifactVerificationReport,
    BacktestArtifactVerificationRequest,
    BacktestCatalogIntegrityReport,
    BacktestIntegrityCode,
    BacktestIntegritySeverity,
)
from quant_platform.backtest.observations import (
    contains_operative_language,
    hash_policy_output_mapping,
)
from quant_platform.backtest.results import hash_backtest_mapping
from quant_platform.backtest.types import (
    ALLOWED_POLICY_NAMES,
    MANIFEST_ARTIFACT_NAME,
    POLICY_OUTPUT_ARTIFACT_NAME,
    SUMMARY_ARTIFACT_NAME,
    BacktestRunCatalogFilters,
    build_backtest_run_catalog_filters,
)
from quant_platform.research.snapshots import (
    hash_manifest_mapping,
    is_sha256_digest,
    manifest_contains_secrets,
)
from quant_platform.simulation.run_types import artifact_path_is_unsafe

_COUNT_FIELDS = (
    "event_count",
    "market_event_count",
    "session_event_count",
    "corporate_action_event_count",
    "warning_count",
    "error_count",
)
_ID_FIELDS = (
    "backtest_id",
    "replay_id",
    "stream_hash",
    "backtest_hash",
    "policy_name",
    "policy_output_hash",
)


def backtest_integrity_json(report: BacktestArtifactVerificationReport) -> str:
    return json.dumps(report.as_mapping(), indent=2, sort_keys=True, ensure_ascii=True)


def backtest_catalog_integrity_json(report: BacktestCatalogIntegrityReport) -> str:
    return json.dumps(report.as_mapping(), indent=2, sort_keys=True, ensure_ascii=True)


def verify_backtest_artifacts(
    run_dir: Path | str | BacktestArtifactVerificationRequest,
    *,
    expected_backtest_id: str | None = None,
) -> BacktestArtifactVerificationReport:
    """Verify a local backtest folder. Does not write files or touch PostgreSQL."""
    request = _as_request(run_dir, expected_backtest_id=expected_backtest_id)
    root = Path(request.run_root).expanduser()
    issues: list[BacktestArtifactVerificationIssue] = []
    artifacts: list[BacktestArtifactStatus] = []
    if not root.exists() or not root.is_dir():
        issues.append(
            _issue(
                BacktestIntegritySeverity.ERROR,
                BacktestIntegrityCode.MISSING_RUN_DIR,
                "backtest run directory is missing",
                path=str(root),
            )
        )
        return _finish(
            root=root,
            backtest_id=request.expected_backtest_id,
            issues=issues,
            artifacts=(),
        )

    resolved_root = root.resolve()
    manifest_path = resolved_root / MANIFEST_ARTIFACT_NAME
    if not manifest_path.is_file():
        issues.append(
            _issue(
                BacktestIntegritySeverity.ERROR,
                BacktestIntegrityCode.MISSING_MANIFEST,
                "manifest.json is missing",
                path=MANIFEST_ARTIFACT_NAME,
            )
        )
        summary_missing = not (resolved_root / SUMMARY_ARTIFACT_NAME).is_file()
        if summary_missing:
            issues.append(
                _issue(
                    BacktestIntegritySeverity.ERROR,
                    BacktestIntegrityCode.MISSING_SUMMARY,
                    "summary.json is missing",
                    path=SUMMARY_ARTIFACT_NAME,
                )
            )
        return _finish(
            root=root,
            backtest_id=request.expected_backtest_id,
            issues=issues,
            artifacts=(),
        )

    manifest_text = manifest_path.read_text(encoding="utf-8")
    if manifest_contains_secrets(manifest_text):
        issues.append(
            _issue(
                BacktestIntegritySeverity.ERROR,
                BacktestIntegrityCode.SECRET_LIKE_VALUE,
                "manifest contains a secret-like marker",
                path=MANIFEST_ARTIFACT_NAME,
            )
        )
    manifest = _load_object(manifest_text, MANIFEST_ARTIFACT_NAME, issues)
    if manifest is None:
        return _finish(
            root=root,
            backtest_id=request.expected_backtest_id,
            issues=issues,
            artifacts=(),
        )

    backtest_id = _optional_str(manifest.get("backtest_id"))
    replay_id = _optional_str(manifest.get("replay_id"))
    policy_name = _optional_str(manifest.get("policy_name"))
    stored_manifest_hash = _optional_str(manifest.get("manifest_hash"))
    stored_stream_hash = _optional_str(manifest.get("stream_hash"))
    stored_backtest_hash = _optional_str(manifest.get("backtest_hash"))
    stored_policy_output_hash = _optional_str(manifest.get("policy_output_hash"))
    if request.expected_backtest_id is not None and backtest_id != (
        request.expected_backtest_id
    ):
        issues.append(
            _issue(
                BacktestIntegritySeverity.ERROR,
                BacktestIntegrityCode.CATALOG_MANIFEST_MISMATCH,
                "manifest backtest_id does not match the expected id",
                path=MANIFEST_ARTIFACT_NAME,
                expected=request.expected_backtest_id,
                actual=backtest_id,
            )
        )
    if replay_id is None:
        issues.append(
            _issue(
                BacktestIntegritySeverity.ERROR,
                BacktestIntegrityCode.INVALID_JSON,
                "replay_id is required",
                path=MANIFEST_ARTIFACT_NAME,
            )
        )
    if stored_stream_hash is None or not is_sha256_digest(stored_stream_hash):
        issues.append(
            _issue(
                BacktestIntegritySeverity.ERROR,
                BacktestIntegrityCode.INVALID_HASH,
                "stream_hash must be sha256:<64 hex>",
                path=MANIFEST_ARTIFACT_NAME,
                actual=stored_stream_hash,
            )
        )
    if stored_backtest_hash is None or not is_sha256_digest(stored_backtest_hash):
        issues.append(
            _issue(
                BacktestIntegritySeverity.ERROR,
                BacktestIntegrityCode.INVALID_HASH,
                "backtest_hash must be sha256:<64 hex>",
                path=MANIFEST_ARTIFACT_NAME,
                actual=stored_backtest_hash,
            )
        )
    if stored_manifest_hash is None or not is_sha256_digest(stored_manifest_hash):
        issues.append(
            _issue(
                BacktestIntegritySeverity.ERROR,
                BacktestIntegrityCode.INVALID_HASH,
                "manifest_hash must be sha256:<64 hex>",
                path=MANIFEST_ARTIFACT_NAME,
                actual=stored_manifest_hash,
            )
        )
    if stored_policy_output_hash is None or not is_sha256_digest(
        stored_policy_output_hash
    ):
        issues.append(
            _issue(
                BacktestIntegritySeverity.ERROR,
                BacktestIntegrityCode.INVALID_HASH,
                "policy_output_hash must be sha256:<64 hex>",
                path=MANIFEST_ARTIFACT_NAME,
                actual=stored_policy_output_hash,
            )
        )
    if policy_name is None or policy_name not in ALLOWED_POLICY_NAMES:
        issues.append(
            _issue(
                BacktestIntegritySeverity.ERROR,
                BacktestIntegrityCode.UNSUPPORTED_POLICY,
                "policy_name must be a registered research policy",
                path=MANIFEST_ARTIFACT_NAME,
                actual=policy_name,
            )
        )

    recomputed_manifest_hash: str | None = None
    try:
        recomputed_manifest_hash = hash_manifest_mapping(manifest)
        if (
            stored_manifest_hash is not None
            and is_sha256_digest(stored_manifest_hash)
            and recomputed_manifest_hash != stored_manifest_hash
        ):
            issues.append(
                _issue(
                    BacktestIntegritySeverity.ERROR,
                    BacktestIntegrityCode.MANIFEST_HASH_MISMATCH,
                    "manifest_hash does not match the canonical payload",
                    path=MANIFEST_ARTIFACT_NAME,
                    expected=stored_manifest_hash,
                    actual=recomputed_manifest_hash,
                )
            )
    except (TypeError, ValueError):
        issues.append(
            _issue(
                BacktestIntegritySeverity.ERROR,
                BacktestIntegrityCode.INVALID_JSON,
                "manifest payload cannot be hashed",
                path=MANIFEST_ARTIFACT_NAME,
            )
        )

    listed = _listed_artifacts(manifest)
    seen_paths: set[str] = set()
    for name, default_path in (
        ("summary", SUMMARY_ARTIFACT_NAME),
        ("manifest", MANIFEST_ARTIFACT_NAME),
        ("policy_output", POLICY_OUTPUT_ARTIFACT_NAME),
    ):
        path = listed.get(name, default_path)
        seen_paths.add(path)
        artifacts.append(
            _status_for(resolved_root, name=name, relative=path, issues=issues)
        )
    for name, path in listed.items():
        if path in seen_paths:
            continue
        artifacts.append(
            _status_for(resolved_root, name=name, relative=path, issues=issues)
        )

    summary_relative = listed.get("summary", SUMMARY_ARTIFACT_NAME)
    summary_path = (
        None
        if artifact_path_is_unsafe(summary_relative)
        else resolved_root / summary_relative
    )
    summary: dict[str, object] | None = None
    recomputed_backtest_hash: str | None = None
    event_count: int | None = None
    if summary_path is not None and summary_path.is_file():
        summary_text = summary_path.read_text(encoding="utf-8")
        if manifest_contains_secrets(summary_text):
            issues.append(
                _issue(
                    BacktestIntegritySeverity.ERROR,
                    BacktestIntegrityCode.SECRET_LIKE_VALUE,
                    "summary contains a secret-like marker",
                    path=SUMMARY_ARTIFACT_NAME,
                )
            )
        summary = _load_object(summary_text, SUMMARY_ARTIFACT_NAME, issues)
        if summary is not None:
            event_count = _optional_int(summary.get("event_count"))
            _check_summary_counts(summary, issues)
            nested = manifest.get("summary")
            if isinstance(nested, dict):
                _check_summary_vs_manifest(summary, nested, issues)
            for field in _ID_FIELDS:
                left = _optional_str(summary.get(field))
                right = _optional_str(manifest.get(field))
                if left is not None and right is not None and left != right:
                    issues.append(
                        _issue(
                            BacktestIntegritySeverity.ERROR,
                            BacktestIntegrityCode.COUNT_MISMATCH,
                            f"{field} does not match between summary and manifest",
                            path=SUMMARY_ARTIFACT_NAME,
                            expected=right,
                            actual=left,
                        )
                    )
            try:
                recomputed_backtest_hash = hash_backtest_mapping(summary)
            except BacktestError:
                issues.append(
                    _issue(
                        BacktestIntegritySeverity.ERROR,
                        BacktestIntegrityCode.INVALID_JSON,
                        "summary payload cannot be hashed",
                        path=SUMMARY_ARTIFACT_NAME,
                    )
                )
            else:
                if (
                    stored_backtest_hash is not None
                    and is_sha256_digest(stored_backtest_hash)
                    and recomputed_backtest_hash != stored_backtest_hash
                ):
                    issues.append(
                        _issue(
                            BacktestIntegritySeverity.ERROR,
                            BacktestIntegrityCode.BACKTEST_HASH_MISMATCH,
                            "backtest_hash does not match the summary payload",
                            path=SUMMARY_ARTIFACT_NAME,
                            expected=stored_backtest_hash,
                            actual=recomputed_backtest_hash,
                        )
                    )
                summary_hash = _optional_str(summary.get("backtest_hash"))
                if (
                    summary_hash is not None
                    and is_sha256_digest(summary_hash)
                    and recomputed_backtest_hash != summary_hash
                ):
                    issues.append(
                        _issue(
                            BacktestIntegritySeverity.ERROR,
                            BacktestIntegrityCode.BACKTEST_HASH_MISMATCH,
                            "summary backtest_hash does not match the payload",
                            path=SUMMARY_ARTIFACT_NAME,
                            expected=summary_hash,
                            actual=recomputed_backtest_hash,
                        )
                    )
    policy_relative = listed.get("policy_output", POLICY_OUTPUT_ARTIFACT_NAME)
    policy_path = (
        None
        if artifact_path_is_unsafe(policy_relative)
        else resolved_root / policy_relative
    )
    if policy_path is not None and policy_path.is_file():
        policy_text = policy_path.read_text(encoding="utf-8")
        if manifest_contains_secrets(policy_text):
            issues.append(
                _issue(
                    BacktestIntegritySeverity.ERROR,
                    BacktestIntegrityCode.SECRET_LIKE_VALUE,
                    "policy_output contains a secret-like marker",
                    path=POLICY_OUTPUT_ARTIFACT_NAME,
                )
            )
        if contains_operative_language(policy_text):
            issues.append(
                _issue(
                    BacktestIntegritySeverity.ERROR,
                    BacktestIntegrityCode.UNSUPPORTED_POLICY,
                    "policy_output contains investment-decision wording",
                    path=POLICY_OUTPUT_ARTIFACT_NAME,
                )
            )
        policy_payload = _load_object(policy_text, POLICY_OUTPUT_ARTIFACT_NAME, issues)
        if policy_payload is not None:
            try:
                recomputed_policy_hash = hash_policy_output_mapping(policy_payload)
            except BacktestError:
                issues.append(
                    _issue(
                        BacktestIntegritySeverity.ERROR,
                        BacktestIntegrityCode.INVALID_JSON,
                        "policy_output payload cannot be hashed",
                        path=POLICY_OUTPUT_ARTIFACT_NAME,
                    )
                )
            else:
                stored = stored_policy_output_hash
                file_hash = _optional_str(policy_payload.get("policy_output_hash"))
                if stored is not None and stored != recomputed_policy_hash:
                    issues.append(
                        _issue(
                            BacktestIntegritySeverity.ERROR,
                            BacktestIntegrityCode.POLICY_OUTPUT_HASH_MISMATCH,
                            "policy_output_hash does not match policy_output.json",
                            path=POLICY_OUTPUT_ARTIFACT_NAME,
                            expected=stored,
                            actual=recomputed_policy_hash,
                        )
                    )
                if file_hash is not None and file_hash != recomputed_policy_hash:
                    issues.append(
                        _issue(
                            BacktestIntegritySeverity.ERROR,
                            BacktestIntegrityCode.POLICY_OUTPUT_HASH_MISMATCH,
                            "stored policy_output_hash does not match payload",
                            path=POLICY_OUTPUT_ARTIFACT_NAME,
                            expected=file_hash,
                            actual=recomputed_policy_hash,
                        )
                    )
    return _finish(
        root=root,
        backtest_id=backtest_id or request.expected_backtest_id,
        replay_id=replay_id,
        issues=issues,
        artifacts=tuple(artifacts),
        stream_hash=stored_stream_hash,
        backtest_hash=stored_backtest_hash,
        recomputed_backtest_hash=recomputed_backtest_hash,
        manifest_hash=stored_manifest_hash,
        recomputed_manifest_hash=recomputed_manifest_hash,
        policy_name=policy_name,
        event_count=event_count,
        policy_output_hash=stored_policy_output_hash,
    )


def verify_registered_backtest_run(
    session: Session,
    backtest_id: str,
    base_dir: Path | str,
) -> BacktestArtifactVerificationReport:
    """Verify local artifacts and compare them to the catalog row."""
    cleaned = backtest_id.strip()
    entry = get_backtest_run_by_id(session, cleaned) if cleaned else None
    run_root = resolve_backtest_run_directory(base_dir, cleaned) if cleaned else None
    if run_root is None:
        issues = [
            _issue(
                BacktestIntegritySeverity.ERROR,
                BacktestIntegrityCode.MISSING_RUN_DIR,
                "backtest run directory could not be resolved",
                path=str(base_dir),
                expected=cleaned or None,
            )
        ]
        if entry is None:
            issues.append(
                _issue(
                    BacktestIntegritySeverity.ERROR,
                    BacktestIntegrityCode.CATALOG_ENTRY_MISSING,
                    "backtest_id is not registered",
                    expected=cleaned or None,
                )
            )
        return _finish(
            root=Path(base_dir),
            backtest_id=cleaned or None,
            issues=issues,
            artifacts=(),
        )
    report = verify_backtest_artifacts(run_root, expected_backtest_id=cleaned)
    issues = list(report.issues)
    if entry is None:
        issues.append(
            _issue(
                BacktestIntegritySeverity.ERROR,
                BacktestIntegrityCode.CATALOG_ENTRY_MISSING,
                "backtest_id is not registered",
            )
        )
        return replace_issues(report, issues)
    if report.stream_hash is not None and entry.stream_hash != report.stream_hash:
        issues.append(
            _issue(
                BacktestIntegritySeverity.ERROR,
                BacktestIntegrityCode.CATALOG_MANIFEST_MISMATCH,
                "catalog stream_hash does not match local manifest",
                expected=entry.stream_hash,
                actual=report.stream_hash,
            )
        )
    if report.backtest_hash is not None and entry.backtest_hash != report.backtest_hash:
        issues.append(
            _issue(
                BacktestIntegritySeverity.ERROR,
                BacktestIntegrityCode.CATALOG_MANIFEST_MISMATCH,
                "catalog backtest_hash does not match local manifest",
                expected=entry.backtest_hash,
                actual=report.backtest_hash,
            )
        )
    if report.manifest_hash is not None and entry.manifest_hash != report.manifest_hash:
        issues.append(
            _issue(
                BacktestIntegritySeverity.ERROR,
                BacktestIntegrityCode.CATALOG_MANIFEST_MISMATCH,
                "catalog manifest_hash does not match local manifest",
                expected=entry.manifest_hash,
                actual=report.manifest_hash,
            )
        )
    if report.event_count is not None and entry.event_count != report.event_count:
        issues.append(
            _issue(
                BacktestIntegritySeverity.ERROR,
                BacktestIntegrityCode.CATALOG_MANIFEST_MISMATCH,
                "catalog event_count does not match local summary",
                expected=str(entry.event_count),
                actual=str(report.event_count),
            )
        )
    if report.policy_name is not None and entry.policy_name != report.policy_name:
        issues.append(
            _issue(
                BacktestIntegritySeverity.ERROR,
                BacktestIntegrityCode.CATALOG_MANIFEST_MISMATCH,
                "catalog policy_name does not match local manifest",
                expected=entry.policy_name,
                actual=report.policy_name,
            )
        )
    if (
        report.policy_output_hash is not None
        and entry.policy_output_hash is not None
        and entry.policy_output_hash != report.policy_output_hash
    ):
        issues.append(
            _issue(
                BacktestIntegritySeverity.ERROR,
                BacktestIntegrityCode.CATALOG_MANIFEST_MISMATCH,
                "catalog policy_output_hash does not match local manifest",
                expected=entry.policy_output_hash,
                actual=report.policy_output_hash,
            )
        )
    return replace_issues(report, issues)


def verify_backtest_catalog(
    session: Session,
    base_dir: Path | str,
    filters: BacktestRunCatalogFilters | None = None,
    *,
    replay_id: str | None = None,
    usable_only: bool = False,
    policy_name: str | None = None,
) -> BacktestCatalogIntegrityReport:
    """Verify catalog rows against local folders under ``base_dir``. Read-only."""
    query = filters
    if query is None:
        query = build_backtest_run_catalog_filters(
            replay_id=replay_id,
            usable_only=usable_only,
            policy_name=policy_name,
        )
    entries = list_backtest_runs(session, query)
    reports = tuple(
        verify_registered_backtest_run(session, entry.backtest_id, base_dir)
        for entry in entries
    )
    error_count = sum(item.error_count for item in reports)
    warning_count = sum(item.warning_count for item in reports)
    return BacktestCatalogIntegrityReport(
        base_dir=str(Path(base_dir)),
        entry_count=len(entries),
        verified_count=sum(1 for item in reports if item.ok),
        error_count=error_count,
        warning_count=warning_count,
        ok=error_count == 0,
        reports=reports,
    )


def resolve_backtest_run_directory(
    base_dir: Path | str, backtest_id: str
) -> Path | None:
    """Find a backtest-run folder for ``backtest_id`` under ``base_dir``."""
    cleaned = backtest_id.strip()
    if not cleaned:
        return None
    base = Path(base_dir).expanduser()
    if not base.exists() or base.is_file():
        return None
    direct = base / MANIFEST_ARTIFACT_NAME
    if direct.is_file() and _manifest_file_backtest_id(direct) == cleaned:
        return base
    named = base / cleaned
    named_manifest = named / MANIFEST_ARTIFACT_NAME
    if (
        named_manifest.is_file()
        and _manifest_file_backtest_id(named_manifest) == cleaned
    ):
        return named
    if not base.is_dir():
        return None
    matches: list[Path] = []
    for child in sorted(base.iterdir()):
        if not child.is_dir():
            continue
        manifest = child / MANIFEST_ARTIFACT_NAME
        if manifest.is_file() and _manifest_file_backtest_id(manifest) == cleaned:
            matches.append(child)
    if len(matches) == 1:
        return matches[0]
    return None


def replace_issues(
    report: BacktestArtifactVerificationReport,
    issues: list[BacktestArtifactVerificationIssue],
) -> BacktestArtifactVerificationReport:
    ranked = _rank(issues)
    error_count = sum(
        1 for item in ranked if item.severity == BacktestIntegritySeverity.ERROR
    )
    warning_count = sum(
        1 for item in ranked if item.severity == BacktestIntegritySeverity.WARNING
    )
    info_count = sum(
        1 for item in ranked if item.severity == BacktestIntegritySeverity.INFO
    )
    return BacktestArtifactVerificationReport(
        run_root=report.run_root,
        backtest_id=report.backtest_id,
        replay_id=report.replay_id,
        ok=error_count == 0,
        error_count=error_count,
        warning_count=warning_count,
        info_count=info_count,
        issues=ranked,
        artifacts=report.artifacts,
        stream_hash=report.stream_hash,
        backtest_hash=report.backtest_hash,
        recomputed_backtest_hash=report.recomputed_backtest_hash,
        manifest_hash=report.manifest_hash,
        recomputed_manifest_hash=report.recomputed_manifest_hash,
        policy_name=report.policy_name,
        event_count=report.event_count,
        policy_output_hash=report.policy_output_hash,
    )


def _as_request(
    run_dir: Path | str | BacktestArtifactVerificationRequest,
    *,
    expected_backtest_id: str | None,
) -> BacktestArtifactVerificationRequest:
    if isinstance(run_dir, BacktestArtifactVerificationRequest):
        if expected_backtest_id is None:
            return run_dir
        return BacktestArtifactVerificationRequest(
            run_root=run_dir.run_root,
            expected_backtest_id=expected_backtest_id,
        )
    return BacktestArtifactVerificationRequest(
        run_root=Path(run_dir),
        expected_backtest_id=expected_backtest_id,
    )


def _load_object(
    text: str,
    path: str,
    issues: list[BacktestArtifactVerificationIssue],
) -> dict[str, object] | None:
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        issues.append(
            _issue(
                BacktestIntegritySeverity.ERROR,
                BacktestIntegrityCode.INVALID_JSON,
                f"{path} is not valid JSON",
                path=path,
            )
        )
        return None
    if not isinstance(loaded, dict):
        issues.append(
            _issue(
                BacktestIntegritySeverity.ERROR,
                BacktestIntegrityCode.INVALID_JSON,
                f"{path} must be an object",
                path=path,
            )
        )
        return None
    return dict(loaded)


def _check_summary_counts(
    summary: Mapping[str, object],
    issues: list[BacktestArtifactVerificationIssue],
) -> None:
    warning_count = _optional_int(summary.get("warning_count"))
    error_count = _optional_int(summary.get("error_count"))
    warnings = summary.get("warnings")
    errors = summary.get("errors")
    if warning_count is not None and isinstance(warnings, list):
        if warning_count != len(warnings):
            issues.append(
                _issue(
                    BacktestIntegritySeverity.ERROR,
                    BacktestIntegrityCode.COUNT_MISMATCH,
                    "warning_count does not match warnings list",
                    path=SUMMARY_ARTIFACT_NAME,
                    expected=str(warning_count),
                    actual=str(len(warnings)),
                )
            )
    if error_count is not None and isinstance(errors, list):
        if error_count != len(errors):
            issues.append(
                _issue(
                    BacktestIntegritySeverity.ERROR,
                    BacktestIntegrityCode.COUNT_MISMATCH,
                    "error_count does not match errors list",
                    path=SUMMARY_ARTIFACT_NAME,
                    expected=str(error_count),
                    actual=str(len(errors)),
                )
            )
    for field in _COUNT_FIELDS:
        value = _optional_int(summary.get(field))
        if value is not None and value < 0:
            issues.append(
                _issue(
                    BacktestIntegritySeverity.ERROR,
                    BacktestIntegrityCode.COUNT_MISMATCH,
                    f"{field} must be >= 0",
                    path=SUMMARY_ARTIFACT_NAME,
                    actual=str(value),
                )
            )


def _check_summary_vs_manifest(
    summary: Mapping[str, object],
    nested: Mapping[str, object],
    issues: list[BacktestArtifactVerificationIssue],
) -> None:
    for field in (*_COUNT_FIELDS, "started_event_seen", "finished_event_seen"):
        left = summary.get(field)
        right = nested.get(field)
        if left is not None and right is not None and left != right:
            issues.append(
                _issue(
                    BacktestIntegritySeverity.ERROR,
                    BacktestIntegrityCode.COUNT_MISMATCH,
                    f"{field} does not match between summary.json and manifest.summary",
                    path=SUMMARY_ARTIFACT_NAME,
                    expected=str(right),
                    actual=str(left),
                )
            )


def _listed_artifacts(manifest: Mapping[str, object]) -> dict[str, str]:
    raw = manifest.get("artifacts")
    listed: dict[str, str] = {}
    if not isinstance(raw, list):
        return listed
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        path = item.get("path")
        if isinstance(name, str) and isinstance(path, str) and name and path:
            listed[name] = path
    return listed


def _status_for(
    root: Path,
    *,
    name: str,
    relative: str,
    issues: list[BacktestArtifactVerificationIssue],
) -> BacktestArtifactStatus:
    unsafe = artifact_path_is_unsafe(relative)
    escaped = ".." in Path(relative).parts
    absolute = Path(relative).is_absolute()
    if not relative.strip():
        issues.append(
            _issue(
                BacktestIntegritySeverity.ERROR,
                BacktestIntegrityCode.EMPTY_ARTIFACT_PATH,
                "artifact path is empty",
                path=name,
            )
        )
    elif absolute:
        issues.append(
            _issue(
                BacktestIntegritySeverity.ERROR,
                BacktestIntegrityCode.ABSOLUTE_PATH,
                "artifact path must be relative",
                path=relative,
            )
        )
    elif escaped:
        issues.append(
            _issue(
                BacktestIntegritySeverity.ERROR,
                BacktestIntegrityCode.PATH_ESCAPE,
                "artifact path must not contain '..'",
                path=relative,
            )
        )
    exists = False
    if not unsafe:
        exists = (root / relative).is_file()
        if not exists:
            code = (
                BacktestIntegrityCode.MISSING_SUMMARY
                if Path(relative).name == SUMMARY_ARTIFACT_NAME or name == "summary"
                else BacktestIntegrityCode.MISSING_MANIFEST
                if Path(relative).name == MANIFEST_ARTIFACT_NAME or name == "manifest"
                else BacktestIntegrityCode.MISSING_ARTIFACT
            )
            issues.append(
                _issue(
                    BacktestIntegritySeverity.ERROR,
                    code,
                    f"{relative} is missing",
                    path=relative,
                )
            )
    return BacktestArtifactStatus(
        name=name,
        path=relative,
        exists=exists,
        relative=not absolute,
        escaped=escaped,
    )


def _manifest_file_backtest_id(path: Path) -> str | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    raw = payload.get("backtest_id")
    if not isinstance(raw, str) or not raw.strip():
        return None
    return raw.strip()


def _issue(
    severity: BacktestIntegritySeverity,
    code: BacktestIntegrityCode,
    message: str,
    *,
    path: str | None = None,
    expected: str | None = None,
    actual: str | None = None,
) -> BacktestArtifactVerificationIssue:
    return BacktestArtifactVerificationIssue(
        severity=severity.value,
        code=code.value,
        message=message,
        path=path,
        expected=expected,
        actual=actual,
    )


def _optional_str(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _rank(
    issues: list[BacktestArtifactVerificationIssue],
) -> tuple[BacktestArtifactVerificationIssue, ...]:
    return tuple(
        sorted(
            issues,
            key=lambda item: (
                SEVERITY_RANK.get(item.severity, 9),
                item.code,
                item.message,
            ),
        )
    )


def _finish(
    *,
    root: Path,
    backtest_id: str | None,
    issues: list[BacktestArtifactVerificationIssue],
    artifacts: tuple[BacktestArtifactStatus, ...],
    replay_id: str | None = None,
    stream_hash: str | None = None,
    backtest_hash: str | None = None,
    recomputed_backtest_hash: str | None = None,
    manifest_hash: str | None = None,
    recomputed_manifest_hash: str | None = None,
    policy_name: str | None = None,
    event_count: int | None = None,
    policy_output_hash: str | None = None,
) -> BacktestArtifactVerificationReport:
    ranked = _rank(issues)
    error_count = sum(
        1 for item in ranked if item.severity == BacktestIntegritySeverity.ERROR
    )
    warning_count = sum(
        1 for item in ranked if item.severity == BacktestIntegritySeverity.WARNING
    )
    info_count = sum(
        1 for item in ranked if item.severity == BacktestIntegritySeverity.INFO
    )
    return BacktestArtifactVerificationReport(
        run_root=str(root),
        backtest_id=backtest_id,
        replay_id=replay_id,
        ok=error_count == 0,
        error_count=error_count,
        warning_count=warning_count,
        info_count=info_count,
        issues=ranked,
        artifacts=artifacts,
        stream_hash=stream_hash,
        backtest_hash=backtest_hash,
        recomputed_backtest_hash=recomputed_backtest_hash,
        manifest_hash=manifest_hash,
        recomputed_manifest_hash=recomputed_manifest_hash,
        policy_name=policy_name,
        event_count=event_count,
        policy_output_hash=policy_output_hash,
    )
