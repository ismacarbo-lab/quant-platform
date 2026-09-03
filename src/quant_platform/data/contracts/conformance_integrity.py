"""Read-only checks for local data-contract conformance artifacts."""

from __future__ import annotations

import json
import re
from pathlib import Path

from quant_platform.data.contracts.conformance import (
    hash_data_contract_conformance_report,
)
from quant_platform.data.contracts.conformance_types import (
    CONFORMANCE_MANIFEST_ARTIFACT_NAME,
    CONFORMANCE_REPORT_ARTIFACT_NAME,
    DataContractConformanceIntegrityReport,
    DataContractConformanceIssue,
)
from quant_platform.data.contracts.hashing import is_sha256_digest
from quant_platform.simulation.run_types import artifact_path_is_unsafe

_TOKEN_URL = re.compile(
    r"(?i)https?://[^\s]*[?&](?:api_key|apikey|token|access_token|password|secret)="
)
_FORBIDDEN_METRIC = re.compile(
    r"(?i)\b(sharpe|drawdown|hit_ratio|hit ratio|exposure)\b"
)
_SECRET_MARKERS = (
    "DATABASE_URL",
    "POSTGRES_PASSWORD",
    "postgresql://",
    "postgres://",
    "postgresql+psycopg://",
)
_VALIDATION_CODES = frozenset(
    {
        "lookahead",
        "naive_timestamp",
        "invalid_ohlc",
        "empty_symbol",
        "secret_in_metadata",
        "token_url",
    }
)


def verify_data_contract_conformance_artifacts(
    run_dir: Path | str,
) -> DataContractConformanceIntegrityReport:
    """Verify a local conformance folder. Does not write files or use the DB."""
    root = Path(run_dir)
    issues: list[DataContractConformanceIssue] = []
    if not root.exists() or not root.is_dir():
        issues.append(_issue("missing_run_dir", "conformance directory is missing"))
        return _finish(issues)

    manifest_path = root / CONFORMANCE_MANIFEST_ARTIFACT_NAME
    report_path = root / CONFORMANCE_REPORT_ARTIFACT_NAME
    if not manifest_path.is_file():
        issues.append(_issue("missing_manifest", "manifest is missing"))
    if not report_path.is_file():
        issues.append(_issue("missing_report", "report is missing"))
    if issues:
        return _finish(issues)

    manifest_text = manifest_path.read_text(encoding="utf-8")
    report_text = report_path.read_text(encoding="utf-8")
    issues.extend(_scan_blob(manifest_text, field="manifest"))
    issues.extend(_scan_blob(report_text, field="report"))
    try:
        manifest = json.loads(manifest_text)
        report = json.loads(report_text)
    except json.JSONDecodeError:
        issues.append(_issue("invalid_json", "artifact JSON is invalid"))
        return _finish(issues)
    if not isinstance(manifest, dict) or not isinstance(report, dict):
        issues.append(_issue("invalid_json", "artifact JSON must be an object"))
        return _finish(issues)

    summary = report.get("summary")
    summary_map = summary if isinstance(summary, dict) else {}
    for field, value in (
        ("manifest.conformance_hash", manifest.get("conformance_hash")),
        ("manifest.batch_hash", manifest.get("batch_hash")),
        ("report.conformance_hash", report.get("conformance_hash")),
        ("report.batch_hash", summary_map.get("batch_hash")),
    ):
        if not isinstance(value, str) or not is_sha256_digest(value):
            issues.append(_issue("invalid_hash", f"{field} is not a sha256 digest"))

    if (
        isinstance(manifest.get("conformance_hash"), str)
        and isinstance(report.get("conformance_hash"), str)
        and manifest["conformance_hash"] != report["conformance_hash"]
    ):
        issues.append(
            _issue("hash_mismatch", "manifest and report conformance_hash differ")
        )
    report_batch = summary_map.get("batch_hash")
    if (
        isinstance(manifest.get("batch_hash"), str)
        and isinstance(report_batch, str)
        and manifest["batch_hash"] != report_batch
    ):
        issues.append(_issue("hash_mismatch", "manifest and report batch_hash differ"))

    try:
        recomputed = hash_data_contract_conformance_report(report)
    except Exception:
        recomputed = None
        issues.append(_issue("invalid_hash", "report hash could not be recomputed"))
    stored = report.get("conformance_hash")
    if isinstance(stored, str) and recomputed is not None and stored != recomputed:
        issues.append(
            _issue("hash_mismatch", "stored conformance_hash does not match content")
        )

    artifacts = manifest.get("artifacts")
    if isinstance(artifacts, list):
        for item in artifacts:
            if not isinstance(item, dict):
                continue
            path = item.get("path")
            if not isinstance(path, str) or artifact_path_is_unsafe(path):
                issues.append(
                    _issue(
                        "path_escape",
                        "artifact path must be relative and must not traverse",
                    )
                )
                continue
            if Path(path).is_absolute():
                issues.append(_issue("absolute_path", "artifact path is absolute"))
            if not (root / path).is_file():
                issues.append(_issue("missing_artifact", f"artifact {path} is missing"))

    report_issues = report.get("issues")
    issue_count = manifest.get("issue_count")
    if isinstance(issue_count, int) and isinstance(report_issues, list):
        if issue_count != len(report_issues):
            issues.append(
                _issue("count_mismatch", "manifest issue_count does not match report")
            )
    summary_counts = summary_map.get("issue_counts")
    if (
        isinstance(summary_counts, dict)
        and isinstance(summary_counts.get("total"), int)
        and isinstance(report_issues, list)
        and summary_counts["total"] != len(report_issues)
    ):
        issues.append(
            _issue("count_mismatch", "summary issue_counts.total does not match")
        )

    validation_ok = summary_map.get("validation_ok")
    offline_ok = summary_map.get("offline_only_ok")
    forbidden_ok = summary_map.get("forbidden_terms_ok")
    report_ok = report.get("ok")
    if isinstance(report_issues, list):
        codes = {item.get("code") for item in report_issues if isinstance(item, dict)}
        if validation_ok is True and (codes & _VALIDATION_CODES):
            issues.append(
                _issue(
                    "flag_mismatch",
                    "validation_ok is true but blocking validation issues exist",
                )
            )
        if forbidden_ok is True and "forbidden_term" in codes:
            issues.append(
                _issue(
                    "flag_mismatch",
                    "forbidden_terms_ok is true but forbidden_term issues exist",
                )
            )
        if offline_ok is True and "offline_contract_violation" in codes:
            issues.append(
                _issue(
                    "flag_mismatch",
                    "offline_only_ok is true but offline violations exist",
                )
            )
        if report_ok is True and (
            validation_ok is False or forbidden_ok is False or offline_ok is False
        ):
            issues.append(
                _issue(
                    "flag_mismatch",
                    "report.ok is true but a conformance flag is false",
                )
            )

    payload_counts = summary_map.get("payload_counts")
    manifest_counts = manifest.get("payload_counts")
    if (
        isinstance(payload_counts, dict)
        and isinstance(manifest_counts, dict)
        and payload_counts != manifest_counts
    ):
        issues.append(
            _issue("count_mismatch", "manifest payload_counts do not match the report")
        )

    return _finish(issues)


def _scan_blob(text: str, *, field: str) -> list[DataContractConformanceIssue]:
    issues: list[DataContractConformanceIssue] = []
    lowered = text.lower()
    for marker in _SECRET_MARKERS:
        if marker.lower() in lowered:
            issues.append(
                _issue("secret_in_metadata", f"{field} contains a secret-like value")
            )
            break
    if _TOKEN_URL.search(text):
        issues.append(
            _issue("token_url", f"{field} contains a URL with credential parameters")
        )
    if _FORBIDDEN_METRIC.search(text):
        issues.append(
            _issue(
                "forbidden_metric",
                f"{field} contains a performance metric",
            )
        )
    return issues


def _issue(code: str, message: str) -> DataContractConformanceIssue:
    return DataContractConformanceIssue(code=code, message=message)


def _finish(
    issues: list[DataContractConformanceIssue],
) -> DataContractConformanceIntegrityReport:
    ranked = tuple(issues)
    return DataContractConformanceIntegrityReport(
        ok=not ranked,
        issues=ranked,
        error_count=len(ranked),
    )
