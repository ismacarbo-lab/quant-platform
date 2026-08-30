"""Read-only checks for local normalization artifacts. Not a repair tool."""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from io import StringIO
from pathlib import Path

from quant_platform.research.normalization.types import (
    BARS_ARTIFACT_NAME,
    MANIFEST_ARTIFACT_NAME,
    REPORT_ARTIFACT_NAME,
    NormalizationIssue,
)
from quant_platform.research.snapshots import (
    is_sha256_digest,
    manifest_contains_secrets,
)
from quant_platform.simulation.run_types import artifact_path_is_unsafe

_FORBIDDEN_METRIC_TOKENS = (
    "sharpe",
    "drawdown",
    "hit_ratio",
    "hit ratio",
    "pnl",
    "returns",
    "portfolio",
    "order",
    "trade",
)
_OPERATIVE_PATTERN = re.compile(
    r"\b(buy|sell|hold|signal|weight|target|order|trade|pnl|return|"
    r"returns|position|portfolio|fill|alpha|exposure|recommendation)\b",
    re.IGNORECASE,
)


class NormalizationIntegritySeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class NormalizationIntegrityCode(StrEnum):
    MISSING_MANIFEST = "missing_manifest"
    MISSING_REPORT = "missing_report"
    MISSING_CSV = "missing_csv"
    INVALID_JSON = "invalid_json"
    ABSOLUTE_PATH = "absolute_path"
    PATH_ESCAPE = "path_escape"
    SECRET_LIKE_VALUE = "secret_like_value"  # noqa: S105
    INVALID_HASH = "invalid_hash"
    HASH_MISMATCH = "hash_mismatch"
    COUNT_MISMATCH = "count_mismatch"
    FORBIDDEN_METRIC = "forbidden_metric"
    OPERATIVE_LANGUAGE = "operative_language"
    MISSING_RUN_DIR = "missing_run_dir"


@dataclass(frozen=True, slots=True)
class NormalizationIntegrityReport:
    ok: bool
    dataset_hash: str | None
    raw_dataset_hash: str | None
    bar_count: int | None
    error_count: int
    warning_count: int
    issues: tuple[NormalizationIssue, ...]

    def as_mapping(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "dataset_hash": self.dataset_hash,
            "raw_dataset_hash": self.raw_dataset_hash,
            "bar_count": self.bar_count,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "issues": [item.as_mapping() for item in self.issues],
        }


def verify_normalization_artifacts(
    run_dir: Path | str,
) -> NormalizationIntegrityReport:
    """Verify a local normalization folder. Does not write files or use the DB."""
    root = Path(run_dir)
    issues: list[NormalizationIssue] = []
    if not root.exists() or not root.is_dir():
        issues.append(
            _error(
                NormalizationIntegrityCode.MISSING_RUN_DIR,
                "normalization directory is missing",
            )
        )
        return _finish(issues)

    manifest_path = root / MANIFEST_ARTIFACT_NAME
    report_path = root / REPORT_ARTIFACT_NAME
    csv_path = root / BARS_ARTIFACT_NAME
    if not manifest_path.is_file():
        issues.append(
            _error(NormalizationIntegrityCode.MISSING_MANIFEST, "manifest is missing")
        )
    if not report_path.is_file():
        issues.append(
            _error(NormalizationIntegrityCode.MISSING_REPORT, "report is missing")
        )
    if not csv_path.is_file():
        issues.append(_error(NormalizationIntegrityCode.MISSING_CSV, "CSV is missing"))
    if any(item.severity == "error" for item in issues):
        return _finish(issues)

    manifest_text = manifest_path.read_text(encoding="utf-8")
    report_text = report_path.read_text(encoding="utf-8")
    csv_text = csv_path.read_text(encoding="utf-8")
    for blob, label in (
        (manifest_text, "manifest"),
        (report_text, "report"),
        (csv_text, "csv"),
    ):
        issues.extend(_scan_text(blob, label=label))

    try:
        manifest = json.loads(manifest_text)
    except json.JSONDecodeError:
        issues.append(
            _error(NormalizationIntegrityCode.INVALID_JSON, "manifest is not JSON")
        )
        return _finish(issues)
    try:
        report = json.loads(report_text)
    except json.JSONDecodeError:
        issues.append(
            _error(NormalizationIntegrityCode.INVALID_JSON, "report is not JSON")
        )
        return _finish(issues)
    if not isinstance(manifest, dict) or not isinstance(report, dict):
        issues.append(
            _error(
                NormalizationIntegrityCode.INVALID_JSON,
                "artifact JSON must be an object",
            )
        )
        return _finish(issues)

    dataset_hash = manifest.get("dataset_hash")
    raw_hash = manifest.get("raw_dataset_hash")
    for field, value in (
        ("dataset_hash", dataset_hash),
        ("raw_dataset_hash", raw_hash),
        ("report.dataset_hash", report.get("dataset_hash")),
        ("report.raw_dataset_hash", report.get("raw_dataset_hash")),
    ):
        if not isinstance(value, str) or not is_sha256_digest(value):
            issues.append(
                _error(
                    NormalizationIntegrityCode.INVALID_HASH,
                    f"{field} is not a sha256 digest",
                )
            )
    if (
        isinstance(dataset_hash, str)
        and isinstance(report.get("dataset_hash"), str)
        and dataset_hash != report["dataset_hash"]
    ):
        issues.append(
            _error(
                NormalizationIntegrityCode.HASH_MISMATCH,
                "manifest and report dataset_hash differ",
            )
        )

    reader = csv.DictReader(StringIO(csv_text))
    data_rows = sum(1 for _ in reader)
    bar_count = manifest.get("bar_count")
    report_count = report.get("bar_count")
    if not isinstance(bar_count, int):
        issues.append(
            _error(
                NormalizationIntegrityCode.COUNT_MISMATCH,
                "manifest bar_count is missing",
            )
        )
        bar_count = None
    elif bar_count != data_rows:
        issues.append(
            _error(
                NormalizationIntegrityCode.COUNT_MISMATCH,
                "CSV row count does not match manifest bar_count",
            )
        )
    if (
        isinstance(report_count, int)
        and isinstance(bar_count, int)
        and report_count != bar_count
    ):
        issues.append(
            _error(
                NormalizationIntegrityCode.COUNT_MISMATCH,
                "report bar_count does not match manifest",
            )
        )
    issue_count = manifest.get("issue_count")
    reported_issues = report.get("issues")
    if isinstance(issue_count, int) and isinstance(reported_issues, list):
        if issue_count != len(reported_issues):
            issues.append(
                _error(
                    NormalizationIntegrityCode.COUNT_MISMATCH,
                    "manifest issue_count does not match report issues",
                )
            )

    artifacts = manifest.get("artifacts")
    if isinstance(artifacts, list):
        for item in artifacts:
            if not isinstance(item, dict):
                continue
            path = item.get("path")
            if not isinstance(path, str):
                issues.append(
                    _error(
                        NormalizationIntegrityCode.PATH_ESCAPE,
                        "artifact path is missing",
                    )
                )
                continue
            if artifact_path_is_unsafe(path):
                code = (
                    NormalizationIntegrityCode.ABSOLUTE_PATH
                    if Path(path).is_absolute()
                    else NormalizationIntegrityCode.PATH_ESCAPE
                )
                issues.append(_error(code, "artifact path is not a safe relative path"))
            elif not (root / path).is_file():
                issues.append(
                    _error(
                        NormalizationIntegrityCode.MISSING_CSV
                        if path.endswith(".csv")
                        else NormalizationIntegrityCode.MISSING_REPORT,
                        f"listed artifact {path} is missing",
                    )
                )

    return _finish(
        issues,
        dataset_hash=dataset_hash if isinstance(dataset_hash, str) else None,
        raw_dataset_hash=raw_hash if isinstance(raw_hash, str) else None,
        bar_count=bar_count if isinstance(bar_count, int) else None,
    )


def _scan_text(blob: str, *, label: str) -> list[NormalizationIssue]:
    issues: list[NormalizationIssue] = []
    if manifest_contains_secrets(blob):
        issues.append(
            _error(
                NormalizationIntegrityCode.SECRET_LIKE_VALUE,
                f"{label} contains a secret-like marker",
            )
        )
    if _OPERATIVE_PATTERN.search(blob):
        issues.append(
            _error(
                NormalizationIntegrityCode.OPERATIVE_LANGUAGE,
                f"{label} contains forbidden decision wording",
            )
        )
    lowered = blob.lower()
    for token in _FORBIDDEN_METRIC_TOKENS:
        if token in lowered:
            issues.append(
                _error(
                    NormalizationIntegrityCode.FORBIDDEN_METRIC,
                    f"{label} contains forbidden metric language",
                )
            )
            break
    return issues


def _error(code: str, message: str) -> NormalizationIssue:
    return NormalizationIssue(code=code, message=message, severity="error")


def _finish(
    issues: list[NormalizationIssue],
    *,
    dataset_hash: str | None = None,
    raw_dataset_hash: str | None = None,
    bar_count: int | None = None,
) -> NormalizationIntegrityReport:
    error_count = sum(1 for item in issues if item.severity == "error")
    warning_count = sum(1 for item in issues if item.severity == "warning")
    return NormalizationIntegrityReport(
        ok=error_count == 0,
        dataset_hash=dataset_hash,
        raw_dataset_hash=raw_dataset_hash,
        bar_count=bar_count,
        error_count=error_count,
        warning_count=warning_count,
        issues=tuple(issues),
    )
