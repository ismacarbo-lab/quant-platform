"""Verify a local research evidence bundle. Read-only; not trading."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from quant_platform.backtest.observations import contains_operative_language
from quant_platform.data.contracts.intake_integrity import (
    verify_contract_payload_intake_artifacts,
)
from quant_platform.release.evidence_bundle import hash_research_evidence_bundle
from quant_platform.release.evidence_types import (
    ALLOWED_FIXTURE_DATA_MODES,
    DEFAULT_CONTRACT_INTAKE_OUTPUT_DIR_NAME,
    EVIDENCE_MANIFEST_NAME,
    EVIDENCE_SUMMARY_NAME,
    NORMALIZED_DATASET_DIRNAME,
    RELEASE_STATUS_NAME,
)
from quant_platform.research.normalization.integrity import (
    verify_normalization_artifacts,
)
from quant_platform.research.snapshots import (
    is_sha256_digest,
    manifest_contains_secrets,
)
from quant_platform.simulation.constructs import detect_trading_constructs
from quant_platform.simulation.run_types import artifact_path_is_unsafe

EVIDENCE_INTEGRITY_KIND = "research_evidence_bundle_integrity"
EVIDENCE_INTEGRITY_FORMAT_VERSION = 1

_HASH_FIELDS = (
    "snapshot_hash",
    "stream_hash",
    "backtest_hash",
    "experiment_hash",
    "report_hash",
    "release_report_hash",
    "bundle_hash",
    "normalized_dataset_hash",
    "contract_intake_hash",
    "contract_intake_batch_hash",
)

_FORBIDDEN_METRIC_TOKENS = (
    "sharpe",
    "drawdown",
    "hit_ratio",
    "hit ratio",
    "pnl",
    "returns",
)


class EvidenceIntegritySeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class EvidenceIntegrityCode(StrEnum):
    MISSING_MANIFEST = "missing_manifest"
    MISSING_SUMMARY = "missing_summary"
    MISSING_RELEASE_STATUS = "missing_release_status"
    INVALID_JSON = "invalid_json"
    ABSOLUTE_PATH = "absolute_path"
    PATH_ESCAPE = "path_escape"
    SECRET_LIKE_VALUE = "secret_like_value"  # noqa: S105
    INVALID_HASH = "invalid_hash"
    HASH_MISMATCH = "hash_mismatch"
    MISSING_ARTIFACT = "missing_artifact"
    STEP_COUNT_MISMATCH = "step_count_mismatch"
    FORBIDDEN_METRIC = "forbidden_metric"
    OPERATIVE_LANGUAGE = "operative_language"
    TRADING_CONSTRUCT = "trading_construct"
    INVALID_FIXTURE_DATA_MODE = "invalid_fixture_data_mode"
    NEGATIVE_REUSE_COUNT = "negative_reuse_count"
    FIXTURE_DATA_FAILED = "fixture_data_failed"
    CONTRACT_INTAKE_MISSING = "contract_intake_missing"
    CONTRACT_INTAKE_WRITE_MISMATCH = "contract_intake_write_mismatch"


@dataclass(frozen=True, slots=True)
class EvidenceIntegrityIssue:
    severity: str
    code: str
    message: str

    def as_mapping(self) -> dict[str, object]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class EvidenceIntegrityReport:
    ok: bool
    bundle_dir: str
    bundle_hash: str | None
    recomputed_bundle_hash: str | None
    error_count: int
    warning_count: int
    issues: tuple[EvidenceIntegrityIssue, ...]

    def as_mapping(self) -> dict[str, object]:
        return {
            "kind": EVIDENCE_INTEGRITY_KIND,
            "format_version": EVIDENCE_INTEGRITY_FORMAT_VERSION,
            "ok": self.ok,
            "bundle_dir": self.bundle_dir,
            "bundle_hash": self.bundle_hash,
            "recomputed_bundle_hash": self.recomputed_bundle_hash,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "issues": [item.as_mapping() for item in self.issues],
        }


def verify_research_evidence_bundle(bundle_dir: Path | str) -> EvidenceIntegrityReport:
    """Read-only checks of a local evidence bundle. Does not trade."""
    root = Path(bundle_dir)
    issues: list[EvidenceIntegrityIssue] = []
    manifest_payload: dict[str, object] | None = None
    summary_payload: dict[str, object] | None = None
    stored_hash: str | None = None
    recomputed: str | None = None

    manifest_path = root / EVIDENCE_MANIFEST_NAME
    summary_path = root / EVIDENCE_SUMMARY_NAME
    release_path = root / RELEASE_STATUS_NAME
    if not manifest_path.is_file():
        issues.append(
            _error(
                EvidenceIntegrityCode.MISSING_MANIFEST,
                "evidence_manifest.json is missing",
            )
        )
    if not summary_path.is_file():
        issues.append(
            _error(
                EvidenceIntegrityCode.MISSING_SUMMARY,
                "evidence_summary.json is missing",
            )
        )
    if not release_path.is_file():
        issues.append(
            _error(
                EvidenceIntegrityCode.MISSING_RELEASE_STATUS,
                "release_status.json is missing",
            )
        )

    if manifest_path.is_file():
        manifest_payload = _load_json(manifest_path, issues, "evidence_manifest.json")
    if summary_path.is_file():
        summary_payload = _load_json(summary_path, issues, "evidence_summary.json")
    if release_path.is_file():
        _load_json(release_path, issues, "release_status.json")

    for payload, label in (
        (manifest_payload, "evidence_manifest.json"),
        (summary_payload, "evidence_summary.json"),
    ):
        if payload is None:
            continue
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=True)
        if manifest_contains_secrets(blob):
            issues.append(
                _error(
                    EvidenceIntegrityCode.SECRET_LIKE_VALUE,
                    f"{label} contains a secret-like value",
                )
            )
        if contains_operative_language(blob):
            issues.append(
                _error(
                    EvidenceIntegrityCode.OPERATIVE_LANGUAGE,
                    f"{label} contains investment-decision wording",
                )
            )
        lowered = blob.lower()
        for token in _FORBIDDEN_METRIC_TOKENS:
            if token in lowered:
                issues.append(
                    _error(
                        EvidenceIntegrityCode.FORBIDDEN_METRIC,
                        f"{label} contains a forbidden research metric",
                    )
                )
                break
        _check_paths(payload, root, issues)

    findings = detect_trading_constructs()
    if findings:
        issues.append(
            _error(
                EvidenceIntegrityCode.TRADING_CONSTRUCT,
                "trading constructs were detected in the research package",
            )
        )

    if manifest_payload is not None:
        stored_hash = _optional_hash(manifest_payload.get("bundle_hash"), issues)
        for field in _HASH_FIELDS:
            raw = manifest_payload.get(field)
            if raw is None or raw == "":
                continue
            if not isinstance(raw, str) or not is_sha256_digest(raw):
                issues.append(
                    _error(
                        EvidenceIntegrityCode.INVALID_HASH,
                        f"{field} is not a sha256 digest",
                    )
                )
        try:
            recomputed = hash_research_evidence_bundle(manifest_payload)
        except Exception:
            issues.append(
                _error(
                    EvidenceIntegrityCode.INVALID_HASH,
                    "evidence bundle hash could not be recomputed",
                )
            )
        if (
            stored_hash is not None
            and recomputed is not None
            and stored_hash != recomputed
        ):
            issues.append(
                _error(
                    EvidenceIntegrityCode.HASH_MISMATCH,
                    "bundle_hash does not match the recomputed digest",
                )
            )
        _check_step_counts(manifest_payload, issues)
        if summary_payload is not None:
            _check_step_counts(summary_payload, issues)
        _check_fixture_data(manifest_payload, issues)
        if summary_payload is not None:
            _check_fixture_data(summary_payload, issues)
        if manifest_payload.get("normalized_dataset_hash"):
            _check_normalized_dataset(root, issues)
        if manifest_payload.get("contract_intake_included") is True:
            _check_contract_intake(manifest_payload, root, issues)

    error_count = sum(
        1 for item in issues if item.severity == EvidenceIntegritySeverity.ERROR
    )
    warning_count = sum(
        1 for item in issues if item.severity == EvidenceIntegritySeverity.WARNING
    )
    return EvidenceIntegrityReport(
        ok=error_count == 0,
        bundle_dir=root.name,
        bundle_hash=stored_hash,
        recomputed_bundle_hash=recomputed,
        error_count=error_count,
        warning_count=warning_count,
        issues=tuple(issues),
    )


def evidence_integrity_json(report: EvidenceIntegrityReport) -> str:
    return json.dumps(report.as_mapping(), indent=2, sort_keys=True, ensure_ascii=True)


def _load_json(
    path: Path, issues: list[EvidenceIntegrityIssue], label: str
) -> dict[str, object] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        issues.append(
            _error(EvidenceIntegrityCode.INVALID_JSON, f"{label} is not valid JSON")
        )
        return None
    if not isinstance(payload, dict):
        issues.append(
            _error(EvidenceIntegrityCode.INVALID_JSON, f"{label} must be an object")
        )
        return None
    return payload


def _check_paths(
    payload: Mapping[str, object],
    root: Path,
    issues: list[EvidenceIntegrityIssue],
) -> None:
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list):
        return
    for item in artifacts:
        if not isinstance(item, Mapping):
            issues.append(
                _error(
                    EvidenceIntegrityCode.INVALID_JSON,
                    "each artifact must be an object",
                )
            )
            continue
        raw = item.get("path")
        if not isinstance(raw, str) or not raw.strip():
            issues.append(
                _error(
                    EvidenceIntegrityCode.MISSING_ARTIFACT,
                    "artifact path is empty",
                )
            )
            continue
        path = raw.strip().replace("\\", "/")
        candidate = Path(path)
        if candidate.is_absolute():
            issues.append(
                _error(
                    EvidenceIntegrityCode.ABSOLUTE_PATH,
                    "artifact paths must be relative",
                )
            )
            continue
        if ".." in candidate.parts:
            issues.append(
                _error(
                    EvidenceIntegrityCode.PATH_ESCAPE,
                    "artifact paths must not traverse parent directories",
                )
            )
            continue
        if artifact_path_is_unsafe(path):
            issues.append(
                _error(
                    EvidenceIntegrityCode.PATH_ESCAPE,
                    "artifact path is not safe",
                )
            )
            continue
        target = (root / path).resolve()
        try:
            target.relative_to(root.resolve())
        except ValueError:
            issues.append(
                _error(
                    EvidenceIntegrityCode.PATH_ESCAPE,
                    "artifact path escaped the bundle directory",
                )
            )
            continue
        if not target.is_file():
            issues.append(
                _error(
                    EvidenceIntegrityCode.MISSING_ARTIFACT,
                    f"declared artifact is missing: {path}",
                )
            )


def _check_step_counts(
    payload: Mapping[str, object], issues: list[EvidenceIntegrityIssue]
) -> None:
    steps = payload.get("steps")
    if not isinstance(steps, list):
        return
    declared = payload.get("step_count")
    if declared is not None and declared != len(steps):
        issues.append(
            _error(
                EvidenceIntegrityCode.STEP_COUNT_MISMATCH,
                "step_count does not match the steps list",
            )
        )
    errors = payload.get("errors")
    error_count = payload.get("error_count")
    if (
        isinstance(errors, list)
        and error_count is not None
        and error_count != len(errors)
    ):
        issues.append(
            _error(
                EvidenceIntegrityCode.STEP_COUNT_MISMATCH,
                "error_count does not match the errors list",
            )
        )
    ok = payload.get("ok")
    if ok is True and isinstance(errors, list) and errors:
        issues.append(
            _error(
                EvidenceIntegrityCode.STEP_COUNT_MISMATCH,
                "ok is true but errors are present",
            )
        )


def _check_normalized_dataset(
    root: Path,
    issues: list[EvidenceIntegrityIssue],
) -> None:
    target = root / NORMALIZED_DATASET_DIRNAME
    if not target.is_dir():
        issues.append(
            _error(
                EvidenceIntegrityCode.MISSING_ARTIFACT,
                "normalized_dataset directory is missing",
            )
        )
        return
    report = verify_normalization_artifacts(target)
    if not report.ok:
        issues.append(
            _error(
                EvidenceIntegrityCode.HASH_MISMATCH,
                "normalized dataset artifacts failed verification",
            )
        )


def _check_contract_intake(
    payload: Mapping[str, object],
    root: Path,
    issues: list[EvidenceIntegrityIssue],
) -> None:
    write_db = payload.get("contract_intake_write_db")
    if not isinstance(write_db, bool):
        issues.append(
            _error(
                EvidenceIntegrityCode.CONTRACT_INTAKE_WRITE_MISMATCH,
                "contract_intake_write_db must be a boolean",
            )
        )
    intake_hash = payload.get("contract_intake_hash")
    batch_hash = payload.get("contract_intake_batch_hash")
    if not isinstance(intake_hash, str) or not is_sha256_digest(intake_hash):
        issues.append(
            _error(
                EvidenceIntegrityCode.INVALID_HASH,
                "contract_intake_hash is not a sha256 digest",
            )
        )
    if not isinstance(batch_hash, str) or not is_sha256_digest(batch_hash):
        issues.append(
            _error(
                EvidenceIntegrityCode.INVALID_HASH,
                "contract_intake_batch_hash is not a sha256 digest",
            )
        )
    inserted = payload.get("contract_intake_inserted_counts")
    inserted_total = _intake_count_total(
        inserted, issues, "contract_intake_inserted_counts"
    )
    if write_db is False and inserted_total is not None and inserted_total > 0:
        issues.append(
            _error(
                EvidenceIntegrityCode.CONTRACT_INTAKE_WRITE_MISMATCH,
                "dry-run contract intake must have inserted_counts total 0",
            )
        )
    dirname = _contract_intake_dir_name(payload)
    target = root / dirname
    if not target.is_dir():
        issues.append(
            _error(
                EvidenceIntegrityCode.CONTRACT_INTAKE_MISSING,
                "contract_payload_intake directory is missing",
            )
        )
        return
    report = verify_contract_payload_intake_artifacts(target)
    if not report.ok:
        issues.append(
            _error(
                EvidenceIntegrityCode.HASH_MISMATCH,
                "contract intake artifacts failed verification",
            )
        )


def _contract_intake_dir_name(payload: Mapping[str, object]) -> str:
    artifacts = payload.get("contract_intake_artifacts")
    if isinstance(artifacts, list):
        for item in artifacts:
            if not isinstance(item, Mapping):
                continue
            raw = item.get("path")
            if not isinstance(raw, str) or not raw.strip():
                continue
            path = raw.strip().replace("\\", "/")
            if "/" in path:
                return path.split("/", 1)[0]
    return DEFAULT_CONTRACT_INTAKE_OUTPUT_DIR_NAME


def _intake_count_total(
    value: object,
    issues: list[EvidenceIntegrityIssue],
    field: str,
) -> int | None:
    if value is None:
        return 0
    if not isinstance(value, Mapping):
        issues.append(
            _error(
                EvidenceIntegrityCode.CONTRACT_INTAKE_WRITE_MISMATCH,
                f"{field} must be an object",
            )
        )
        return None
    total = value.get("total")
    if total is None:
        return 0
    if not isinstance(total, int) or isinstance(total, bool) or total < 0:
        issues.append(
            _error(
                EvidenceIntegrityCode.NEGATIVE_REUSE_COUNT,
                f"{field} total must be a non-negative integer",
            )
        )
        return None
    return total


def _check_fixture_data(
    payload: Mapping[str, object], issues: list[EvidenceIntegrityIssue]
) -> None:
    mode = payload.get("fixture_data_mode")
    if mode is None or mode == "":
        return
    if not isinstance(mode, str) or mode not in ALLOWED_FIXTURE_DATA_MODES:
        issues.append(
            _error(
                EvidenceIntegrityCode.INVALID_FIXTURE_DATA_MODE,
                "fixture_data_mode must be inserted, reused, or failed",
            )
        )
        return
    if mode == "failed" and payload.get("ok") is True:
        issues.append(
            _error(
                EvidenceIntegrityCode.FIXTURE_DATA_FAILED,
                "fixture_data_mode is failed but the bundle is marked ok",
            )
        )
    reuse = payload.get("fixture_reuse")
    if reuse is None:
        return
    if not isinstance(reuse, Mapping):
        issues.append(
            _error(
                EvidenceIntegrityCode.INVALID_FIXTURE_DATA_MODE,
                "fixture_reuse must be an object",
            )
        )
        return
    for field in (
        "inserted_bar_count",
        "reused_bar_count",
        "inserted_corporate_action_count",
        "reused_corporate_action_count",
        "inserted_session_count",
        "reused_session_count",
    ):
        value = reuse.get(field)
        if value is None:
            continue
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            issues.append(
                _error(
                    EvidenceIntegrityCode.NEGATIVE_REUSE_COUNT,
                    f"{field} must be a non-negative integer",
                )
            )


def _optional_hash(value: object, issues: list[EvidenceIntegrityIssue]) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not is_sha256_digest(value):
        issues.append(
            _error(
                EvidenceIntegrityCode.INVALID_HASH,
                "bundle_hash is not a sha256 digest",
            )
        )
        return None
    return value


def _error(code: EvidenceIntegrityCode, message: str) -> EvidenceIntegrityIssue:
    return EvidenceIntegrityIssue(
        severity=EvidenceIntegritySeverity.ERROR.value,
        code=code.value,
        message=message,
    )
