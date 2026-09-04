"""Deterministic contract-payload intake regression. No database, no trading."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

from quant_platform.data.contracts.errors import (
    VendorContractError,
    VendorContractErrorCode,
)
from quant_platform.data.contracts.fake_provider import (
    load_offline_vendor_payload_batch,
)
from quant_platform.data.contracts.hashing import sha256_canonical_mapping
from quant_platform.data.contracts.intake import (
    build_contract_payload_intake_plan,
    build_contract_payload_intake_request,
)
from quant_platform.data.contracts.intake_regression_types import (
    BATCH_FIXTURE_NAME,
    EXPECTED_DRIFT_CODES,
    EXPECTED_FIXTURE_NAME,
    INTAKE_REGRESSION_HASH_FORMAT_VERSION,
    INTAKE_REGRESSION_HASH_KIND,
    REQUEST_FIXTURE_NAME,
    IntakeRegressionActual,
    IntakeRegressionCase,
    IntakeRegressionCode,
    IntakeRegressionExpected,
    IntakeRegressionIssue,
    IntakeRegressionMatrixReport,
    IntakeRegressionResult,
    IntakeRegressionSeverity,
)
from quant_platform.simulation.run_types import artifact_path_is_unsafe

_REQUIRED_CASE_FILES = (
    BATCH_FIXTURE_NAME,
    REQUEST_FIXTURE_NAME,
    EXPECTED_FIXTURE_NAME,
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


def default_contract_payload_intake_dir() -> Path:
    """Resolve ``tests/fixtures/contract_payload_intake`` from the repository."""
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "tests" / "fixtures" / "contract_payload_intake"
        if candidate.is_dir():
            return candidate
    raise VendorContractError(
        "contract payload intake fixtures directory is missing",
        code=VendorContractErrorCode.FIXTURE_UNREADABLE,
    )


def load_intake_regression_case(path: Path | str) -> IntakeRegressionCase:
    """Parse one golden case directory. Does not run intake."""
    root = Path(path)
    case_id = root.name
    if artifact_path_is_unsafe(case_id):
        raise VendorContractError(
            "intake regression case path must be a relative directory name",
            code=VendorContractErrorCode.FIXTURE_UNREADABLE,
        )
    expected_payload = _load_json_object(root / EXPECTED_FIXTURE_NAME, required=False)
    return IntakeRegressionCase(
        case_id=case_id,
        fixture_dir=case_id,
        expected=_expected_from_mapping(expected_payload),
    )


def run_intake_regression_case(
    case: IntakeRegressionCase,
    *,
    fixtures_root: Path | str | None = None,
) -> IntakeRegressionResult:
    root = (
        Path(fixtures_root)
        if fixtures_root is not None
        else default_contract_payload_intake_dir()
    )
    case_dir = root / case.fixture_dir
    issues: list[IntakeRegressionIssue] = []
    for name in _REQUIRED_CASE_FILES:
        if not (case_dir / name).is_file():
            issues.append(
                _issue(
                    IntakeRegressionSeverity.ERROR,
                    IntakeRegressionCode.MISSING_FIXTURE,
                    f"{name} is missing",
                    path=str(Path(case.fixture_dir) / name),
                )
            )
    if issues:
        return IntakeRegressionResult(
            case_id=case.case_id,
            fixture_dir=case.fixture_dir,
            passed=False,
            actual=None,
            expected=case.expected,
            issues=tuple(issues),
        )
    try:
        for name in _REQUIRED_CASE_FILES:
            issues.extend(_scan_fixture_text(case_dir / name, case.fixture_dir))
        batch = load_offline_vendor_payload_batch(case_dir / BATCH_FIXTURE_NAME)
        request_payload = _load_json_object(
            case_dir / REQUEST_FIXTURE_NAME, required=True
        )
        if request_payload is None:
            raise VendorContractError(
                "request.json is missing",
                code=VendorContractErrorCode.FIXTURE_UNREADABLE,
            )
        request = build_contract_payload_intake_request(
            contract_name=str(
                request_payload.get("contract_name") or "vendor_agnostic_data_source"
            ),
            contract_version=str(request_payload.get("contract_version") or "1"),
            source_name=(
                None
                if request_payload.get("source_name") is None
                else str(request_payload.get("source_name"))
            ),
            created_by=str(
                request_payload.get("created_by") or "offline_intake_runner"
            ),
            notes=(
                None
                if request_payload.get("notes") is None
                else str(request_payload.get("notes"))
            ),
            write_db=bool(request_payload.get("write_db", False)),
            allow_invalid=bool(request_payload.get("allow_invalid", False)),
            include_source_payload=bool(
                request_payload.get("include_source_payload", False)
            ),
        )
        plan = build_contract_payload_intake_plan(batch, request)
    except VendorContractError as exc:
        issues.append(
            _issue(
                IntakeRegressionSeverity.ERROR,
                IntakeRegressionCode.INVALID_FIXTURE,
                str(exc),
                path=case.fixture_dir,
            )
        )
        return IntakeRegressionResult(
            case_id=case.case_id,
            fixture_dir=case.fixture_dir,
            passed=False,
            actual=None,
            expected=case.expected,
            issues=tuple(issues),
        )
    except Exception as exc:
        issues.append(
            _issue(
                IntakeRegressionSeverity.ERROR,
                IntakeRegressionCode.UNEXPECTED_ERROR,
                type(exc).__name__,
                path=case.fixture_dir,
            )
        )
        return IntakeRegressionResult(
            case_id=case.case_id,
            fixture_dir=case.fixture_dir,
            passed=False,
            actual=None,
            expected=case.expected,
            issues=tuple(issues),
        )
    actual = IntakeRegressionActual(
        case_id=case.case_id,
        intake_hash=plan.intake_hash,
        batch_hash=plan.batch_hash,
        conformance_hash=plan.conformance_hash,
        issue_count=len(plan.issues),
        issue_codes=tuple(sorted({str(item.code) for item in plan.issues})),
        ok=plan.ok,
        write_db=plan.write_db,
        allow_invalid=plan.allow_invalid,
        planned_daily_bar_count=plan.planned_daily_bar_count,
        planned_corporate_action_count=plan.planned_corporate_action_count,
        planned_market_session_count=plan.planned_market_session_count,
    )
    issues.extend(compare_intake_regression_result(actual, case.expected))
    blocking = any(
        item.severity == IntakeRegressionSeverity.ERROR.value for item in issues
    )
    return IntakeRegressionResult(
        case_id=case.case_id,
        fixture_dir=case.fixture_dir,
        passed=not blocking,
        actual=actual,
        expected=case.expected,
        issues=tuple(issues),
    )


def run_contract_payload_intake_regression(
    root_dir: Path | str | None = None,
) -> IntakeRegressionMatrixReport:
    """Run every case directory. Does not write artifacts or touch PostgreSQL."""
    root = default_contract_payload_intake_dir() if root_dir is None else Path(root_dir)
    if not root.is_dir():
        raise VendorContractError(
            "contract payload intake fixtures directory is missing",
            code=VendorContractErrorCode.FIXTURE_UNREADABLE,
        )
    case_dirs = sorted(
        item
        for item in root.iterdir()
        if item.is_dir() and not item.name.startswith(".")
    )
    if not case_dirs:
        raise VendorContractError(
            "contract payload intake fixtures directory has no cases",
            code=VendorContractErrorCode.FIXTURE_UNREADABLE,
        )
    results = [
        run_intake_regression_case(
            load_intake_regression_case(item),
            fixtures_root=root,
        )
        for item in case_dirs
    ]
    ranked = tuple(sorted(results, key=lambda item: item.case_id))
    error_count = sum(
        1
        for result in ranked
        for issue in result.issues
        if issue.severity == IntakeRegressionSeverity.ERROR.value
    )
    warning_count = sum(
        1
        for result in ranked
        for issue in result.issues
        if issue.severity == IntakeRegressionSeverity.WARNING.value
    )
    passed_count = sum(1 for result in ranked if result.passed)
    draft = IntakeRegressionMatrixReport(
        case_count=len(ranked),
        passed_count=passed_count,
        failed_count=len(ranked) - passed_count,
        error_count=error_count,
        warning_count=warning_count,
        results=ranked,
        report_hash="",
        ok=error_count == 0 and passed_count == len(ranked),
    )
    return replace(draft, report_hash=hash_intake_regression_report(draft))


def compare_intake_regression_result(
    actual: IntakeRegressionActual,
    expected: IntakeRegressionExpected,
) -> tuple[IntakeRegressionIssue, ...]:
    issues: list[IntakeRegressionIssue] = []
    if expected.intake_hash is not None and actual.intake_hash != expected.intake_hash:
        issues.append(
            _issue(
                IntakeRegressionSeverity.ERROR,
                IntakeRegressionCode.INTAKE_HASH_CHANGED,
                "intake_hash differs from the golden expected hash",
                expected=expected.intake_hash,
                actual=actual.intake_hash,
            )
        )
    if expected.batch_hash is not None and actual.batch_hash != expected.batch_hash:
        issues.append(
            _issue(
                IntakeRegressionSeverity.ERROR,
                IntakeRegressionCode.BATCH_HASH_CHANGED,
                "batch_hash differs from the golden expected hash",
                expected=expected.batch_hash,
                actual=actual.batch_hash,
            )
        )
    if (
        expected.conformance_hash is not None
        and actual.conformance_hash != expected.conformance_hash
    ):
        issues.append(
            _issue(
                IntakeRegressionSeverity.ERROR,
                IntakeRegressionCode.CONFORMANCE_HASH_CHANGED,
                "conformance_hash differs from the golden expected hash",
                expected=expected.conformance_hash,
                actual=actual.conformance_hash,
            )
        )
    if expected.issue_count is not None and actual.issue_count != expected.issue_count:
        issues.append(
            _issue(
                IntakeRegressionSeverity.ERROR,
                IntakeRegressionCode.ISSUE_COUNT_CHANGED,
                "issue_count differs from the golden expected count",
                expected=str(expected.issue_count),
                actual=_optional_int_text(actual.issue_count),
            )
        )
    if expected.issue_codes is not None:
        if tuple(actual.issue_codes) != tuple(expected.issue_codes):
            issues.append(
                _issue(
                    IntakeRegressionSeverity.ERROR,
                    IntakeRegressionCode.ISSUE_CODES_CHANGED,
                    "issue codes differ from the golden expected set",
                    expected=",".join(expected.issue_codes),
                    actual=",".join(actual.issue_codes),
                )
            )
    if expected.ok is not None and actual.ok != expected.ok:
        issues.append(
            _issue(
                IntakeRegressionSeverity.ERROR,
                IntakeRegressionCode.ISSUE_CODES_CHANGED,
                "ok flag differs from the golden expected value",
                expected=str(expected.ok),
                actual=str(actual.ok),
            )
        )
    if expected.write_db is not None and actual.write_db != expected.write_db:
        issues.append(
            _issue(
                IntakeRegressionSeverity.ERROR,
                IntakeRegressionCode.COUNT_CHANGED,
                "write_db differs from the golden expected value",
                expected=str(expected.write_db),
                actual=str(actual.write_db),
            )
        )
    if (
        expected.allow_invalid is not None
        and actual.allow_invalid != expected.allow_invalid
    ):
        issues.append(
            _issue(
                IntakeRegressionSeverity.ERROR,
                IntakeRegressionCode.COUNT_CHANGED,
                "allow_invalid differs from the golden expected value",
                expected=str(expected.allow_invalid),
                actual=str(actual.allow_invalid),
            )
        )
    if (
        expected.planned_daily_bar_count is not None
        and actual.planned_daily_bar_count != expected.planned_daily_bar_count
    ):
        issues.append(
            _issue(
                IntakeRegressionSeverity.ERROR,
                IntakeRegressionCode.COUNT_CHANGED,
                "planned_daily_bar_count differs from the golden expected count",
                expected=str(expected.planned_daily_bar_count),
                actual=_optional_int_text(actual.planned_daily_bar_count),
            )
        )
    if (
        expected.planned_corporate_action_count is not None
        and actual.planned_corporate_action_count
        != expected.planned_corporate_action_count
    ):
        issues.append(
            _issue(
                IntakeRegressionSeverity.ERROR,
                IntakeRegressionCode.COUNT_CHANGED,
                "planned_corporate_action_count differs from the golden expected count",
                expected=str(expected.planned_corporate_action_count),
                actual=_optional_int_text(actual.planned_corporate_action_count),
            )
        )
    if (
        expected.planned_market_session_count is not None
        and actual.planned_market_session_count != expected.planned_market_session_count
    ):
        issues.append(
            _issue(
                IntakeRegressionSeverity.ERROR,
                IntakeRegressionCode.COUNT_CHANGED,
                "planned_market_session_count differs from the golden expected count",
                expected=str(expected.planned_market_session_count),
                actual=_optional_int_text(actual.planned_market_session_count),
            )
        )
    return tuple(issues)


def hash_intake_regression_report(
    report: IntakeRegressionMatrixReport | Mapping[str, object],
) -> str:
    if isinstance(report, IntakeRegressionMatrixReport):
        payload = report.as_mapping(include_report_hash=False)
    else:
        payload = dict(report)
        payload.pop("report_hash", None)
    results = payload.get("results", [])
    ranked: list[dict[str, object]] = []
    if isinstance(results, list):
        for item in results:
            if isinstance(item, dict):
                ranked.append(_result_digest(item))
        ranked.sort(key=lambda item: _json_sort_key(item))
    digest_payload = {
        "kind": INTAKE_REGRESSION_HASH_KIND,
        "version": INTAKE_REGRESSION_HASH_FORMAT_VERSION,
        "matrix_name": payload.get("matrix_name"),
        "ok": payload.get("ok"),
        "case_count": payload.get("case_count"),
        "passed_count": payload.get("passed_count"),
        "failed_count": payload.get("failed_count"),
        "error_count": payload.get("error_count"),
        "warning_count": payload.get("warning_count"),
        "results": ranked,
    }
    blob = str(digest_payload).lower()
    for marker in _SECRET_MARKERS:
        if marker.lower() in blob:
            raise VendorContractError(
                "intake regression report must not contain secrets",
                code=VendorContractErrorCode.SECRET_IN_METADATA,
            )
    return sha256_canonical_mapping(digest_payload)


def intake_regression_report_has_blocking_errors(
    report: IntakeRegressionMatrixReport,
    *,
    ignore_expected_drift: bool = False,
) -> bool:
    for result in report.results:
        for issue in result.issues:
            if issue.severity != IntakeRegressionSeverity.ERROR.value:
                continue
            if ignore_expected_drift and issue.code in EXPECTED_DRIFT_CODES:
                continue
            return True
    return False


def _json_sort_key(item: Mapping[str, object]) -> str:
    return json.dumps(item, sort_keys=True, separators=(",", ":"), default=str)


def _result_digest(item: Mapping[str, object]) -> dict[str, object]:
    actual = item.get("actual")
    actual_map = dict(actual) if isinstance(actual, dict) else {}
    return {
        "case_id": item.get("case_id"),
        "passed": item.get("passed"),
        "intake_hash": actual_map.get("intake_hash"),
        "batch_hash": actual_map.get("batch_hash"),
        "conformance_hash": actual_map.get("conformance_hash"),
        "issue_count": actual_map.get("issue_count"),
        "issue_codes": actual_map.get("issue_codes"),
        "ok": actual_map.get("ok"),
        "planned_daily_bar_count": actual_map.get("planned_daily_bar_count"),
        "planned_corporate_action_count": actual_map.get(
            "planned_corporate_action_count"
        ),
        "planned_market_session_count": actual_map.get("planned_market_session_count"),
    }


def _expected_from_mapping(
    payload: Mapping[str, object] | None,
) -> IntakeRegressionExpected:
    if payload is None:
        return IntakeRegressionExpected()
    codes_raw = payload.get("expected_issue_codes")
    codes: tuple[str, ...] | None
    if codes_raw is None:
        codes = None
    elif isinstance(codes_raw, list):
        codes = tuple(str(item) for item in codes_raw)
    else:
        codes = (str(codes_raw),)
    return IntakeRegressionExpected(
        intake_hash=_optional_str(payload.get("expected_intake_hash")),
        batch_hash=_optional_str(payload.get("expected_batch_hash")),
        conformance_hash=_optional_str(payload.get("expected_conformance_hash")),
        issue_count=_optional_int(payload.get("expected_issue_count")),
        issue_codes=codes,
        ok=_optional_bool(payload.get("expected_ok")),
        write_db=_optional_bool(payload.get("expected_write_db")),
        allow_invalid=_optional_bool(payload.get("expected_allow_invalid")),
        planned_daily_bar_count=_optional_int(
            payload.get("expected_planned_daily_bar_count")
        ),
        planned_corporate_action_count=_optional_int(
            payload.get("expected_planned_corporate_action_count")
        ),
        planned_market_session_count=_optional_int(
            payload.get("expected_planned_market_session_count")
        ),
    )


def _load_json_object(
    path: Path,
    *,
    required: bool,
) -> dict[str, object] | None:
    if not path.is_file():
        if required:
            raise VendorContractError(
                f"{path.name} is missing",
                code=VendorContractErrorCode.FIXTURE_UNREADABLE,
            )
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise VendorContractError(
            f"{path.name} is not JSON",
            code=VendorContractErrorCode.FIXTURE_UNREADABLE,
        ) from exc
    if not isinstance(raw, dict):
        raise VendorContractError(
            f"{path.name} must be a JSON object",
            code=VendorContractErrorCode.FIXTURE_UNREADABLE,
        )
    return raw


def _scan_fixture_text(path: Path, fixture_dir: str) -> list[IntakeRegressionIssue]:
    text = path.read_text(encoding="utf-8")
    issues: list[IntakeRegressionIssue] = []
    lowered = text.lower()
    for marker in _SECRET_MARKERS:
        if marker.lower() in lowered:
            issues.append(
                _issue(
                    IntakeRegressionSeverity.ERROR,
                    IntakeRegressionCode.INVALID_FIXTURE,
                    f"{path.name} contains a secret-like value",
                    path=str(Path(fixture_dir) / path.name),
                )
            )
            break
    if _FORBIDDEN_METRIC.search(text):
        issues.append(
            _issue(
                IntakeRegressionSeverity.ERROR,
                IntakeRegressionCode.FORBIDDEN_METRIC_DETECTED,
                f"{path.name} contains a performance metric",
                path=str(Path(fixture_dir) / path.name),
            )
        )
    return issues


def _issue(
    severity: IntakeRegressionSeverity,
    code: IntakeRegressionCode,
    message: str,
    *,
    path: str | None = None,
    expected: str | None = None,
    actual: str | None = None,
) -> IntakeRegressionIssue:
    return IntakeRegressionIssue(
        severity=severity.value,
        code=code.value,
        message=message,
        path=path,
        expected=expected,
        actual=actual,
    )


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    token = str(value).strip()
    return token or None


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        return int(value)
    return None


def _optional_bool(value: object) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    token = str(value).strip().lower()
    if token in {"true", "1"}:
        return True
    if token in {"false", "0"}:
        return False
    return None


def _optional_int_text(value: int | None) -> str:
    if value is None:
        return ""
    return str(value)
