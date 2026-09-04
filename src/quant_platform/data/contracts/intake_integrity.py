"""Read-only checks for local contract-payload intake artifacts."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path

from quant_platform.data.contracts.hashing import is_sha256_digest
from quant_platform.data.contracts.intake import (
    hash_contract_payload_intake_plan,
    hash_contract_payload_intake_report,
)
from quant_platform.data.contracts.intake_types import (
    INTAKE_MANIFEST_ARTIFACT_NAME,
    INTAKE_PLAN_ARTIFACT_NAME,
    INTAKE_REPORT_ARTIFACT_NAME,
    ContractPayloadIntakeIntegrityReport,
    ContractPayloadIntakeIssue,
)
from quant_platform.data.contracts.types import FORBIDDEN_VENDOR_IDENTITY_NAMES
from quant_platform.simulation.run_types import artifact_path_is_unsafe

_TOKEN_URL = re.compile(
    r"(?i)https?://[^\s]*[?&](?:api_key|apikey|token|access_token|password|secret)="
)
_FORBIDDEN_METRIC = re.compile(
    r"(?i)\b(sharpe|drawdown|hit_ratio|hit ratio|exposure)\b"
)
_FORBIDDEN_KEYS = frozenset(
    {
        "pnl",
        "returns",
        "sharpe",
        "drawdown",
        "portfolio",
        "orders",
        "fills",
        "hit_ratio",
        "exposure",
    }
)
_SECRET_MARKERS = (
    "DATABASE_URL",
    "POSTGRES_PASSWORD",
    "postgresql://",
    "postgres://",
    "postgresql+psycopg://",
)
_VENDOR_TERM = re.compile(
    r"(?i)\b(?:"
    + "|".join(re.escape(name) for name in sorted(FORBIDDEN_VENDOR_IDENTITY_NAMES))
    + r")\b"
)


def verify_contract_payload_intake_artifacts(
    run_dir: Path | str,
) -> ContractPayloadIntakeIntegrityReport:
    """Verify a local intake folder. Does not write files or use the DB."""
    root = Path(run_dir)
    issues: list[ContractPayloadIntakeIssue] = []
    if not root.exists() or not root.is_dir():
        issues.append(_issue("missing_run_dir", "intake directory is missing"))
        return _finish(issues)

    manifest_path = root / INTAKE_MANIFEST_ARTIFACT_NAME
    plan_path = root / INTAKE_PLAN_ARTIFACT_NAME
    report_path = root / INTAKE_REPORT_ARTIFACT_NAME
    if not manifest_path.is_file():
        issues.append(_issue("missing_manifest", "manifest is missing"))
    if not plan_path.is_file():
        issues.append(_issue("missing_plan", "plan is missing"))
    if not report_path.is_file():
        issues.append(_issue("missing_report", "report is missing"))
    if issues:
        return _finish(issues)

    manifest_text = manifest_path.read_text(encoding="utf-8")
    plan_text = plan_path.read_text(encoding="utf-8")
    report_text = report_path.read_text(encoding="utf-8")
    issues.extend(_scan_blob(manifest_text, field="manifest"))
    issues.extend(_scan_blob(plan_text, field="plan"))
    issues.extend(_scan_blob(report_text, field="report"))
    try:
        manifest = json.loads(manifest_text)
        plan = json.loads(plan_text)
        report = json.loads(report_text)
    except json.JSONDecodeError:
        issues.append(_issue("invalid_json", "artifact JSON is invalid"))
        return _finish(issues)
    if (
        not isinstance(manifest, dict)
        or not isinstance(plan, dict)
        or not isinstance(report, dict)
    ):
        issues.append(_issue("invalid_json", "artifact JSON must be an object"))
        return _finish(issues)

    issues.extend(_scan_forbidden_keys(manifest, field="manifest"))
    issues.extend(_scan_forbidden_keys(plan, field="plan"))
    issues.extend(_scan_forbidden_keys(report, field="report"))

    for field, value in (
        ("manifest.intake_hash", manifest.get("intake_hash")),
        ("manifest.batch_hash", manifest.get("batch_hash")),
        ("manifest.conformance_hash", manifest.get("conformance_hash")),
        ("plan.intake_hash", plan.get("intake_hash")),
        ("plan.batch_hash", plan.get("batch_hash")),
        ("plan.conformance_hash", plan.get("conformance_hash")),
        ("report.intake_hash", report.get("intake_hash")),
        ("report.batch_hash", report.get("batch_hash")),
        ("report.conformance_hash", report.get("conformance_hash")),
    ):
        if not isinstance(value, str) or not is_sha256_digest(value):
            issues.append(_issue("invalid_hash", f"{field} is not a sha256 digest"))

    if manifest.get("intake_hash") != report.get("intake_hash"):
        issues.append(_issue("hash_mismatch", "manifest and report intake_hash differ"))
    if manifest.get("batch_hash") != report.get("batch_hash"):
        issues.append(_issue("hash_mismatch", "manifest and report batch_hash differ"))
    if manifest.get("conformance_hash") != report.get("conformance_hash"):
        issues.append(
            _issue("hash_mismatch", "manifest and report conformance_hash differ")
        )
    if plan.get("batch_hash") != report.get("batch_hash"):
        issues.append(_issue("hash_mismatch", "plan and report batch_hash differ"))
    if plan.get("conformance_hash") != report.get("conformance_hash"):
        issues.append(
            _issue("hash_mismatch", "plan and report conformance_hash differ")
        )

    try:
        recomputed_plan = hash_contract_payload_intake_plan(plan)
    except Exception:
        recomputed_plan = None
        issues.append(_issue("invalid_hash", "plan hash could not be recomputed"))
    stored_plan = plan.get("intake_hash")
    if (
        isinstance(stored_plan, str)
        and recomputed_plan is not None
        and stored_plan != recomputed_plan
    ):
        issues.append(
            _issue("hash_mismatch", "stored plan intake_hash does not match content")
        )

    try:
        recomputed_report = hash_contract_payload_intake_report(report)
    except Exception:
        recomputed_report = None
        issues.append(_issue("invalid_hash", "report hash could not be recomputed"))
    stored_report = report.get("intake_hash")
    if (
        isinstance(stored_report, str)
        and recomputed_report is not None
        and stored_report != recomputed_report
    ):
        issues.append(
            _issue("hash_mismatch", "stored report intake_hash does not match content")
        )

    if "write_db" not in plan or "write_db" not in report or "write_db" not in manifest:
        issues.append(_issue("write_db_missing", "write_db must be explicit"))
    elif not (
        isinstance(plan.get("write_db"), bool)
        and isinstance(report.get("write_db"), bool)
        and isinstance(manifest.get("write_db"), bool)
    ):
        issues.append(_issue("write_db_missing", "write_db must be a boolean"))
    elif plan.get("write_db") != report.get("write_db"):
        issues.append(_issue("flag_mismatch", "plan and report write_db differ"))
    elif manifest.get("write_db") != report.get("write_db"):
        issues.append(_issue("flag_mismatch", "manifest and report write_db differ"))
    if report.get("write_db") is False and report.get("db_executed") is True:
        issues.append(
            _issue("flag_mismatch", "db_executed is true but write_db is false")
        )
    if manifest.get("db_executed") != report.get("db_executed"):
        issues.append(_issue("flag_mismatch", "manifest and report db_executed differ"))

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

    issue_count = manifest.get("issue_count")
    report_issues = report.get("issues")
    if isinstance(issue_count, int) and isinstance(report_issues, list):
        if issue_count != len(report_issues):
            issues.append(
                _issue("count_mismatch", "manifest issue_count does not match report")
            )

    for key in (
        "payload_counts",
        "accepted_counts",
        "rejected_counts",
        "inserted_counts",
        "skipped_counts",
    ):
        if plan.get(key) != report.get(key) and key in {
            "payload_counts",
            "accepted_counts",
            "rejected_counts",
        }:
            if plan.get(key) != report.get(key):
                issues.append(_issue("count_mismatch", f"plan and report {key} differ"))
        if manifest.get(key) != report.get(key) and key in manifest:
            if manifest.get(key) != report.get(key):
                issues.append(
                    _issue("count_mismatch", f"manifest and report {key} differ")
                )

    issues.extend(_count_coherence(plan, report))
    return _finish(issues)


def _count_coherence(
    plan: Mapping[str, object],
    report: Mapping[str, object],
) -> list[ContractPayloadIntakeIssue]:
    issues: list[ContractPayloadIntakeIssue] = []
    payload = plan.get("payload_counts")
    accepted = plan.get("accepted_counts")
    rejected = plan.get("rejected_counts")
    if (
        isinstance(payload, dict)
        and isinstance(accepted, dict)
        and isinstance(rejected, dict)
    ):
        for key in ("daily_bars", "corporate_actions", "market_sessions"):
            total = payload.get(key)
            ok_count = accepted.get(key)
            bad_count = rejected.get(key)
            if (
                isinstance(total, int)
                and isinstance(ok_count, int)
                and isinstance(bad_count, int)
                and total != ok_count + bad_count
            ):
                issues.append(
                    _issue(
                        "count_mismatch",
                        f"{key} accepted+rejected do not match payload_counts",
                    )
                )
    planned_daily = plan.get("planned_daily_bar_count")
    if (
        isinstance(accepted, dict)
        and isinstance(planned_daily, int)
        and accepted.get("daily_bars") != planned_daily
    ):
        issues.append(
            _issue(
                "count_mismatch",
                "planned_daily_bar_count does not match accepted daily bars",
            )
        )
    if report.get("db_executed") is True:
        inserted = report.get("inserted_counts")
        skipped = report.get("skipped_counts")
        if (
            isinstance(inserted, dict)
            and isinstance(skipped, dict)
            and isinstance(accepted, dict)
        ):
            for key in ("daily_bars", "corporate_actions", "market_sessions"):
                ins = inserted.get(key)
                skip = skipped.get(key)
                acc = accepted.get(key)
                if (
                    isinstance(ins, int)
                    and isinstance(skip, int)
                    and isinstance(acc, int)
                    and ins + skip != acc
                ):
                    issues.append(
                        _issue(
                            "count_mismatch",
                            f"{key} inserted+skipped do not match accepted_counts",
                        )
                    )
    return issues


def _scan_blob(text: str, *, field: str) -> list[ContractPayloadIntakeIssue]:
    issues: list[ContractPayloadIntakeIssue] = []
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
            _issue("forbidden_metric", f"{field} contains a performance metric")
        )
    if _VENDOR_TERM.search(text):
        issues.append(
            _issue("real_vendor_name", f"{field} names a real market-data vendor")
        )
    return issues


def _scan_forbidden_keys(
    value: object,
    *,
    field: str,
) -> list[ContractPayloadIntakeIssue]:
    issues: list[ContractPayloadIntakeIssue] = []
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = str(key).strip().lower()
            if lowered in _FORBIDDEN_KEYS:
                issues.append(
                    _issue(
                        "forbidden_term",
                        f"{field} contains a trading or performance key",
                    )
                )
                return issues
            issues.extend(_scan_forbidden_keys(item, field=field))
            if issues:
                return issues
    elif isinstance(value, list):
        for item in value:
            issues.extend(_scan_forbidden_keys(item, field=field))
            if issues:
                return issues
    return issues


def _issue(code: str, message: str) -> ContractPayloadIntakeIssue:
    return ContractPayloadIntakeIssue(code=code, message=message)


def _finish(
    issues: list[ContractPayloadIntakeIssue],
) -> ContractPayloadIntakeIntegrityReport:
    ranked = tuple(issues)
    return ContractPayloadIntakeIntegrityReport(
        ok=not ranked,
        issues=ranked,
        error_count=len(ranked),
    )
