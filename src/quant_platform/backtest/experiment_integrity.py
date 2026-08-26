"""Read-only integrity checks for local experiment artifacts. No writes."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from quant_platform.backtest.experiment_types import (
    EXPERIMENT_MANIFEST_ARTIFACT_NAME,
    EXPERIMENT_RESEARCH_REPORT_ARTIFACT_NAME,
    EXPERIMENT_SUMMARY_ARTIFACT_NAME,
    EXPERIMENT_USABILITY_ARTIFACT_NAME,
    member_relative_path,
)
from quant_platform.backtest.integrity_types import (
    SEVERITY_RANK,
    BacktestArtifactStatus,
    BacktestArtifactVerificationIssue,
    BacktestIntegritySeverity,
)
from quant_platform.backtest.observations import contains_operative_language
from quant_platform.backtest.types import ALLOWED_POLICY_NAMES
from quant_platform.research.snapshots import (
    hash_manifest_mapping,
    is_sha256_digest,
    manifest_contains_secrets,
)
from quant_platform.simulation.run_types import artifact_path_is_unsafe


class ExperimentIntegrityCode(StrEnum):
    MISSING_DIR = "missing_experiment_dir"
    MISSING_MANIFEST = "missing_manifest"
    MISSING_SUMMARY = "missing_summary"
    ABSOLUTE_PATH = "absolute_path"
    PATH_ESCAPE = "path_escape"
    INVALID_HASH = "invalid_hash"
    MANIFEST_HASH_MISMATCH = "manifest_hash_mismatch"
    EXPERIMENT_HASH_MISMATCH = "experiment_hash_mismatch"
    SECRET_LIKE_VALUE = "secret_like_value"  # noqa: S105
    COUNT_MISMATCH = "count_mismatch"
    UNSUPPORTED_POLICY = "unsupported_policy"
    INVALID_JSON = "invalid_json"
    EMPTY_ARTIFACT_PATH = "empty_artifact_path"
    MISSING_ARTIFACT = "missing_artifact"
    MEMBER_BACKTEST_ID_MISMATCH = "member_backtest_id_mismatch"
    FORBIDDEN_OPERATIONAL_LANGUAGE = "forbidden_operational_language"


EXPERIMENT_INTEGRITY_KIND = "backtest_experiment_verification"
EXPERIMENT_INTEGRITY_FORMAT_VERSION = 1

_OPTIONAL_REPORT_ARTIFACTS = frozenset(
    {
        EXPERIMENT_RESEARCH_REPORT_ARTIFACT_NAME,
        EXPERIMENT_USABILITY_ARTIFACT_NAME,
    }
)


@dataclass(frozen=True, slots=True)
class ExperimentArtifactVerificationReport:
    experiment_root: str
    experiment_id: str | None
    ok: bool
    error_count: int
    warning_count: int
    info_count: int
    issues: tuple[BacktestArtifactVerificationIssue, ...]
    artifacts: tuple[BacktestArtifactStatus, ...]
    experiment_hash: str | None
    recomputed_experiment_hash: str | None
    manifest_hash: str | None
    recomputed_manifest_hash: str | None
    policy_name: str | None
    member_count: int | None

    def as_mapping(self) -> dict[str, object]:
        return {
            "kind": EXPERIMENT_INTEGRITY_KIND,
            "format_version": EXPERIMENT_INTEGRITY_FORMAT_VERSION,
            "experiment_root": self.experiment_root,
            "experiment_id": self.experiment_id,
            "ok": self.ok,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "info_count": self.info_count,
            "issues": [item.as_mapping() for item in self.issues],
            "artifacts": [item.as_mapping() for item in self.artifacts],
            "experiment_hash": self.experiment_hash,
            "recomputed_experiment_hash": self.recomputed_experiment_hash,
            "manifest_hash": self.manifest_hash,
            "recomputed_manifest_hash": self.recomputed_manifest_hash,
            "policy_name": self.policy_name,
            "member_count": self.member_count,
        }


def experiment_integrity_json(report: ExperimentArtifactVerificationReport) -> str:
    return json.dumps(report.as_mapping(), indent=2, sort_keys=True, ensure_ascii=True)


def verify_backtest_experiment_artifacts(
    experiment_dir: Path | str,
    *,
    expected_experiment_id: str | None = None,
) -> ExperimentArtifactVerificationReport:
    """Verify a local experiment folder. Does not write files or touch PostgreSQL."""
    from quant_platform.backtest.experiments import (
        hash_experiment_mapping,
        members_from_experiment_summary,
    )

    root = Path(experiment_dir).expanduser()
    issues: list[BacktestArtifactVerificationIssue] = []
    artifacts: list[BacktestArtifactStatus] = []
    if not root.exists() or not root.is_dir():
        issues.append(
            _issue(
                BacktestIntegritySeverity.ERROR,
                ExperimentIntegrityCode.MISSING_DIR,
                "experiment directory is missing",
                path=str(root),
            )
        )
        return _finish(root=root, issues=issues, artifacts=())

    resolved = root.resolve()
    manifest_path = resolved / EXPERIMENT_MANIFEST_ARTIFACT_NAME
    summary_path = resolved / EXPERIMENT_SUMMARY_ARTIFACT_NAME
    if not manifest_path.is_file():
        issues.append(
            _issue(
                BacktestIntegritySeverity.ERROR,
                ExperimentIntegrityCode.MISSING_MANIFEST,
                "experiment_manifest.json is missing",
                path=EXPERIMENT_MANIFEST_ARTIFACT_NAME,
            )
        )
    if not summary_path.is_file():
        issues.append(
            _issue(
                BacktestIntegritySeverity.ERROR,
                ExperimentIntegrityCode.MISSING_SUMMARY,
                "experiment_summary.json is missing",
                path=EXPERIMENT_SUMMARY_ARTIFACT_NAME,
            )
        )
    if not manifest_path.is_file():
        return _finish(root=root, issues=issues, artifacts=())

    manifest_text = manifest_path.read_text(encoding="utf-8")
    _reject_secrets(issues, manifest_text, EXPERIMENT_MANIFEST_ARTIFACT_NAME)
    _reject_operative(issues, manifest_text, EXPERIMENT_MANIFEST_ARTIFACT_NAME)
    manifest = _load_object(manifest_text, EXPERIMENT_MANIFEST_ARTIFACT_NAME, issues)
    if manifest is None:
        return _finish(root=root, issues=issues, artifacts=())

    summary_blob: dict[str, object] | None = None
    if summary_path.is_file():
        summary_text = summary_path.read_text(encoding="utf-8")
        _reject_secrets(issues, summary_text, EXPERIMENT_SUMMARY_ARTIFACT_NAME)
        _reject_operative(issues, summary_text, EXPERIMENT_SUMMARY_ARTIFACT_NAME)
        summary_blob = _load_object(
            summary_text, EXPERIMENT_SUMMARY_ARTIFACT_NAME, issues
        )

    experiment_id = _optional_str(manifest.get("experiment_id"))
    policy_name = _optional_str(manifest.get("policy_name"))
    stored_experiment_hash = _optional_str(manifest.get("experiment_hash"))
    stored_manifest_hash = _optional_str(manifest.get("manifest_hash"))
    if expected_experiment_id is not None and experiment_id != expected_experiment_id:
        issues.append(
            _issue(
                BacktestIntegritySeverity.ERROR,
                ExperimentIntegrityCode.COUNT_MISMATCH,
                "experiment_id does not match the expected value",
                path=EXPERIMENT_MANIFEST_ARTIFACT_NAME,
                expected=expected_experiment_id,
                actual=experiment_id,
            )
        )
    if policy_name is None or policy_name not in ALLOWED_POLICY_NAMES:
        issues.append(
            _issue(
                BacktestIntegritySeverity.ERROR,
                ExperimentIntegrityCode.UNSUPPORTED_POLICY,
                "policy_name must be a registered research policy",
                path=EXPERIMENT_MANIFEST_ARTIFACT_NAME,
                actual=policy_name,
            )
        )
    _require_hash(
        issues,
        stored_experiment_hash,
        "experiment_hash",
        EXPERIMENT_MANIFEST_ARTIFACT_NAME,
    )
    _require_hash(
        issues,
        stored_manifest_hash,
        "manifest_hash",
        EXPERIMENT_MANIFEST_ARTIFACT_NAME,
    )

    nested_summary = manifest.get("summary")
    if not isinstance(nested_summary, dict):
        issues.append(
            _issue(
                BacktestIntegritySeverity.ERROR,
                ExperimentIntegrityCode.INVALID_JSON,
                "manifest.summary must be an object",
                path=EXPERIMENT_MANIFEST_ARTIFACT_NAME,
            )
        )
        nested_summary = {}
    if summary_blob is not None and summary_blob != nested_summary:
        issues.append(
            _issue(
                BacktestIntegritySeverity.ERROR,
                ExperimentIntegrityCode.COUNT_MISMATCH,
                "experiment_summary.json does not match manifest.summary",
                path=EXPERIMENT_SUMMARY_ARTIFACT_NAME,
            )
        )

    members = members_from_experiment_summary(nested_summary)
    member_count = _optional_int(nested_summary.get("member_count"))
    usable_count = _optional_int(nested_summary.get("usable_count"))
    warning_count = _optional_int(nested_summary.get("warning_count"))
    error_count = _optional_int(nested_summary.get("error_count"))
    if member_count is not None and member_count != len(members):
        issues.append(
            _issue(
                BacktestIntegritySeverity.ERROR,
                ExperimentIntegrityCode.COUNT_MISMATCH,
                "member_count does not match members",
                expected=str(len(members)),
                actual=str(member_count),
            )
        )
    actual_usable = sum(1 for item in members if item.usable_result)
    actual_warnings = sum(item.warning_count for item in members)
    actual_errors = sum(item.error_count for item in members)
    if usable_count is not None and usable_count != actual_usable:
        issues.append(
            _issue(
                BacktestIntegritySeverity.ERROR,
                ExperimentIntegrityCode.COUNT_MISMATCH,
                "usable_count does not match members",
                expected=str(actual_usable),
                actual=str(usable_count),
            )
        )
    if warning_count is not None and warning_count != actual_warnings:
        issues.append(
            _issue(
                BacktestIntegritySeverity.ERROR,
                ExperimentIntegrityCode.COUNT_MISMATCH,
                "warning_count does not match members",
                expected=str(actual_warnings),
                actual=str(warning_count),
            )
        )
    if error_count is not None and error_count != actual_errors:
        issues.append(
            _issue(
                BacktestIntegritySeverity.ERROR,
                ExperimentIntegrityCode.COUNT_MISMATCH,
                "error_count does not match members",
                expected=str(actual_errors),
                actual=str(error_count),
            )
        )

    listed = manifest.get("artifacts")
    artifact_rows: list[Mapping[str, object]] = []
    if isinstance(listed, list):
        for item in listed:
            if isinstance(item, dict):
                artifact_rows.append(item)
    for item in artifact_rows:
        status = _artifact_status(resolved, item)
        artifacts.append(status)
        _check_artifact_status(issues, status)
        listed_path = status.path
        if (
            status.exists
            and not status.escaped
            and listed_path in _OPTIONAL_REPORT_ARTIFACTS
        ):
            report_text = (resolved / listed_path).read_text(encoding="utf-8")
            _reject_secrets(issues, report_text, listed_path)
            _reject_operative(issues, report_text, listed_path)

    for index, member in enumerate(members, start=1):
        relative = member.relative_path or member_relative_path(index)
        member_manifest = resolved / relative / "manifest.json"
        if artifact_path_is_unsafe(f"{relative}/manifest.json"):
            issues.append(
                _issue(
                    BacktestIntegritySeverity.ERROR,
                    ExperimentIntegrityCode.PATH_ESCAPE,
                    "member path must be relative",
                    path=relative,
                )
            )
            continue
        if not member_manifest.is_file():
            issues.append(
                _issue(
                    BacktestIntegritySeverity.ERROR,
                    ExperimentIntegrityCode.MISSING_ARTIFACT,
                    "member backtest manifest is missing",
                    path=f"{relative}/manifest.json",
                )
            )
            continue
        loaded = _load_object(
            member_manifest.read_text(encoding="utf-8"),
            f"{relative}/manifest.json",
            issues,
        )
        if loaded is None:
            continue
        found_id = _optional_str(loaded.get("backtest_id"))
        if found_id != member.backtest_id:
            issues.append(
                _issue(
                    BacktestIntegritySeverity.ERROR,
                    ExperimentIntegrityCode.MEMBER_BACKTEST_ID_MISMATCH,
                    "member backtest_id does not match the nested manifest",
                    path=f"{relative}/manifest.json",
                    expected=member.backtest_id,
                    actual=found_id,
                )
            )

    request = manifest.get("request")
    recomputed_experiment_hash: str | None = None
    if isinstance(request, dict):
        recomputed_experiment_hash = hash_experiment_mapping(
            request=request, members=members
        )
        if (
            stored_experiment_hash is not None
            and recomputed_experiment_hash != stored_experiment_hash
        ):
            issues.append(
                _issue(
                    BacktestIntegritySeverity.ERROR,
                    ExperimentIntegrityCode.EXPERIMENT_HASH_MISMATCH,
                    "experiment_hash does not match the recomputed definition",
                    path=EXPERIMENT_MANIFEST_ARTIFACT_NAME,
                    expected=recomputed_experiment_hash,
                    actual=stored_experiment_hash,
                )
            )

    recomputed_manifest_hash = hash_manifest_mapping(manifest)
    if (
        stored_manifest_hash is not None
        and recomputed_manifest_hash != stored_manifest_hash
    ):
        issues.append(
            _issue(
                BacktestIntegritySeverity.ERROR,
                ExperimentIntegrityCode.MANIFEST_HASH_MISMATCH,
                "manifest_hash does not match the recomputed export",
                path=EXPERIMENT_MANIFEST_ARTIFACT_NAME,
                expected=recomputed_manifest_hash,
                actual=stored_manifest_hash,
            )
        )

    return _finish(
        root=root,
        issues=issues,
        artifacts=tuple(artifacts),
        experiment_id=experiment_id,
        experiment_hash=stored_experiment_hash,
        recomputed_experiment_hash=recomputed_experiment_hash,
        manifest_hash=stored_manifest_hash,
        recomputed_manifest_hash=recomputed_manifest_hash,
        policy_name=policy_name,
        member_count=member_count if member_count is not None else len(members),
    )


def resolve_experiment_directory(
    base_dir: Path | str, experiment_id: str
) -> Path | None:
    """Find an experiment folder for ``experiment_id`` under ``base_dir``."""
    cleaned = experiment_id.strip()
    if not cleaned:
        return None
    base = Path(base_dir).expanduser()
    if not base.exists() or base.is_file():
        return None
    direct = base / EXPERIMENT_MANIFEST_ARTIFACT_NAME
    if direct.is_file() and _manifest_file_experiment_id(direct) == cleaned:
        return base
    named = base / cleaned
    named_manifest = named / EXPERIMENT_MANIFEST_ARTIFACT_NAME
    if (
        named_manifest.is_file()
        and _manifest_file_experiment_id(named_manifest) == cleaned
    ):
        return named
    if not base.is_dir():
        return None
    matches: list[Path] = []
    for child in sorted(base.iterdir()):
        if not child.is_dir():
            continue
        manifest = child / EXPERIMENT_MANIFEST_ARTIFACT_NAME
        if manifest.is_file() and _manifest_file_experiment_id(manifest) == cleaned:
            matches.append(child)
    if len(matches) == 1:
        return matches[0]
    return None


def _manifest_file_experiment_id(path: Path) -> str | None:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(loaded, dict):
        return None
    value = loaded.get("experiment_id")
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _reject_secrets(
    issues: list[BacktestArtifactVerificationIssue], text: str, path: str
) -> None:
    if manifest_contains_secrets(text):
        issues.append(
            _issue(
                BacktestIntegritySeverity.ERROR,
                ExperimentIntegrityCode.SECRET_LIKE_VALUE,
                "experiment metadata contains a secret-like marker",
                path=path,
            )
        )


def _reject_operative(
    issues: list[BacktestArtifactVerificationIssue], text: str, path: str
) -> None:
    if contains_operative_language(text):
        issues.append(
            _issue(
                BacktestIntegritySeverity.ERROR,
                ExperimentIntegrityCode.FORBIDDEN_OPERATIONAL_LANGUAGE,
                "experiment metadata contains investment-decision wording",
                path=path,
            )
        )


def _require_hash(
    issues: list[BacktestArtifactVerificationIssue],
    value: str | None,
    field: str,
    path: str,
) -> None:
    if value is None or not is_sha256_digest(value):
        issues.append(
            _issue(
                BacktestIntegritySeverity.ERROR,
                ExperimentIntegrityCode.INVALID_HASH,
                f"{field} must be sha256:<64 hex>",
                path=path,
                actual=value,
            )
        )


def _artifact_status(root: Path, item: Mapping[str, object]) -> BacktestArtifactStatus:
    name = str(item.get("name") or "")
    path = item.get("path")
    relative = isinstance(path, str) and bool(path.strip())
    escaped = True
    exists = False
    path_text = str(path) if isinstance(path, str) else ""
    if relative:
        escaped = artifact_path_is_unsafe(path_text)
        if not escaped:
            exists = (root / path_text).is_file()
    return BacktestArtifactStatus(
        name=name or path_text,
        path=path_text,
        exists=exists,
        relative=relative and not Path(path_text).is_absolute(),
        escaped=escaped or (isinstance(path, str) and Path(path).is_absolute()),
    )


def _check_artifact_status(
    issues: list[BacktestArtifactVerificationIssue],
    status: BacktestArtifactStatus,
) -> None:
    if not status.path.strip():
        issues.append(
            _issue(
                BacktestIntegritySeverity.ERROR,
                ExperimentIntegrityCode.EMPTY_ARTIFACT_PATH,
                "artifact path is empty",
                path=status.name,
            )
        )
        return
    if Path(status.path).is_absolute() or not status.relative:
        issues.append(
            _issue(
                BacktestIntegritySeverity.ERROR,
                ExperimentIntegrityCode.ABSOLUTE_PATH,
                "artifact path must be relative",
                path=status.path,
            )
        )
        return
    if status.escaped:
        issues.append(
            _issue(
                BacktestIntegritySeverity.ERROR,
                ExperimentIntegrityCode.PATH_ESCAPE,
                "artifact path must not contain ..",
                path=status.path,
            )
        )
        return
    if not status.exists:
        issues.append(
            _issue(
                BacktestIntegritySeverity.ERROR,
                ExperimentIntegrityCode.MISSING_ARTIFACT,
                "listed experiment artifact is missing",
                path=status.path,
            )
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
                ExperimentIntegrityCode.INVALID_JSON,
                "file is not valid JSON",
                path=path,
            )
        )
        return None
    if not isinstance(loaded, dict):
        issues.append(
            _issue(
                BacktestIntegritySeverity.ERROR,
                ExperimentIntegrityCode.INVALID_JSON,
                "JSON root must be an object",
                path=path,
            )
        )
        return None
    return loaded


def _optional_str(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _issue(
    severity: BacktestIntegritySeverity,
    code: ExperimentIntegrityCode,
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


def _finish(
    *,
    root: Path,
    issues: list[BacktestArtifactVerificationIssue],
    artifacts: tuple[BacktestArtifactStatus, ...],
    experiment_id: str | None = None,
    experiment_hash: str | None = None,
    recomputed_experiment_hash: str | None = None,
    manifest_hash: str | None = None,
    recomputed_manifest_hash: str | None = None,
    policy_name: str | None = None,
    member_count: int | None = None,
) -> ExperimentArtifactVerificationReport:
    ranked = tuple(
        sorted(
            issues,
            key=lambda item: (
                SEVERITY_RANK.get(item.severity, 9),
                item.code,
                item.message,
            ),
        )
    )
    error_count = sum(
        1 for item in ranked if item.severity == BacktestIntegritySeverity.ERROR
    )
    warning_count = sum(
        1 for item in ranked if item.severity == BacktestIntegritySeverity.WARNING
    )
    info_count = sum(
        1 for item in ranked if item.severity == BacktestIntegritySeverity.INFO
    )
    return ExperimentArtifactVerificationReport(
        experiment_root=str(root),
        experiment_id=experiment_id,
        ok=error_count == 0,
        error_count=error_count,
        warning_count=warning_count,
        info_count=info_count,
        issues=ranked,
        artifacts=artifacts,
        experiment_hash=experiment_hash,
        recomputed_experiment_hash=recomputed_experiment_hash,
        manifest_hash=manifest_hash,
        recomputed_manifest_hash=recomputed_manifest_hash,
        policy_name=policy_name,
        member_count=member_count,
    )
