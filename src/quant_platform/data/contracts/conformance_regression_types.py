"""Typed data-contract conformance regression shapes. Not a PnL check."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

CONFORMANCE_REGRESSION_KIND = "data_contract_conformance_regression_report"
CONFORMANCE_REGRESSION_FORMAT_VERSION = 1
CONFORMANCE_REGRESSION_HASH_KIND = "data_contract_conformance_regression_report"
CONFORMANCE_REGRESSION_HASH_FORMAT_VERSION = 1
CONFORMANCE_REGRESSION_ACTUALS_KIND = "data_contract_conformance_regression_actuals"
CONFORMANCE_REGRESSION_ACTUALS_FORMAT_VERSION = 1

CONFORMANCE_REGRESSION_REPORT_ARTIFACT_NAME = (
    "data_contract_conformance_regression_report.json"
)
CONFORMANCE_REGRESSION_ACTUALS_ARTIFACT_NAME = (
    "data_contract_conformance_regression_actuals.json"
)

BATCH_FIXTURE_NAME = "batch.json"
REQUEST_FIXTURE_NAME = "request.json"
EXPECTED_FIXTURE_NAME = "expected.json"


class ConformanceRegressionSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ConformanceRegressionCode(StrEnum):
    MISSING_FIXTURE = "missing_fixture"
    INVALID_FIXTURE = "invalid_fixture"
    CONFORMANCE_HASH_CHANGED = "conformance_hash_changed"
    BATCH_HASH_CHANGED = "batch_hash_changed"
    ISSUE_COUNT_CHANGED = "issue_count_changed"
    ISSUE_CODES_CHANGED = "issue_codes_changed"
    FORBIDDEN_METRIC_DETECTED = "forbidden_metric_detected"
    OFFLINE_CONTRACT_VIOLATION = "offline_contract_violation"
    UNEXPECTED_ERROR = "unexpected_error"


CONFORMANCE_REGRESSION_SEVERITY_RANK: dict[str, int] = {
    ConformanceRegressionSeverity.ERROR.value: 0,
    ConformanceRegressionSeverity.WARNING.value: 1,
    ConformanceRegressionSeverity.INFO.value: 2,
}

EXPECTED_DRIFT_CODES = frozenset(
    {
        ConformanceRegressionCode.CONFORMANCE_HASH_CHANGED.value,
        ConformanceRegressionCode.BATCH_HASH_CHANGED.value,
        ConformanceRegressionCode.ISSUE_COUNT_CHANGED.value,
        ConformanceRegressionCode.ISSUE_CODES_CHANGED.value,
    }
)


@dataclass(frozen=True, slots=True)
class ConformanceRegressionExpected:
    conformance_hash: str | None = None
    batch_hash: str | None = None
    issue_count: int | None = None
    issue_codes: tuple[str, ...] | None = None
    validation_ok: bool | None = None
    forbidden_terms_ok: bool | None = None
    offline_only_ok: bool | None = None
    ok: bool | None = None

    def as_mapping(self) -> dict[str, object]:
        return {
            "expected_conformance_hash": self.conformance_hash,
            "expected_batch_hash": self.batch_hash,
            "expected_issue_count": self.issue_count,
            "expected_issue_codes": (
                None if self.issue_codes is None else list(self.issue_codes)
            ),
            "expected_validation_ok": self.validation_ok,
            "expected_forbidden_terms_ok": self.forbidden_terms_ok,
            "expected_offline_only_ok": self.offline_only_ok,
            "expected_ok": self.ok,
        }


@dataclass(frozen=True, slots=True)
class ConformanceRegressionCase:
    case_id: str
    fixture_dir: str
    expected: ConformanceRegressionExpected

    def as_mapping(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "case_id": self.case_id,
            "fixture_dir": self.fixture_dir,
        }
        payload.update(self.expected.as_mapping())
        return payload


@dataclass(frozen=True, slots=True)
class ConformanceRegressionActual:
    case_id: str
    conformance_hash: str | None
    batch_hash: str | None
    issue_count: int | None
    issue_codes: tuple[str, ...]
    validation_ok: bool | None
    forbidden_terms_ok: bool | None
    offline_only_ok: bool | None
    ok: bool | None

    def as_mapping(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "conformance_hash": self.conformance_hash,
            "batch_hash": self.batch_hash,
            "issue_count": self.issue_count,
            "issue_codes": list(self.issue_codes),
            "validation_ok": self.validation_ok,
            "forbidden_terms_ok": self.forbidden_terms_ok,
            "offline_only_ok": self.offline_only_ok,
            "ok": self.ok,
        }


@dataclass(frozen=True, slots=True)
class ConformanceRegressionIssue:
    severity: str
    code: str
    message: str
    path: str | None = None
    expected: str | None = None
    actual: str | None = None

    def as_mapping(self) -> dict[str, object]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "path": self.path,
            "expected": self.expected,
            "actual": self.actual,
        }


@dataclass(frozen=True, slots=True)
class ConformanceRegressionResult:
    case_id: str
    fixture_dir: str
    passed: bool
    actual: ConformanceRegressionActual | None
    expected: ConformanceRegressionExpected
    issues: tuple[ConformanceRegressionIssue, ...]

    def as_mapping(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "fixture_dir": self.fixture_dir,
            "passed": self.passed,
            "actual": None if self.actual is None else self.actual.as_mapping(),
            "expected": self.expected.as_mapping(),
            "issues": [item.as_mapping() for item in self.issues],
        }


@dataclass(frozen=True, slots=True)
class ConformanceRegressionArtifact:
    name: str
    path: str
    kind: str = "json"

    def as_mapping(self) -> dict[str, object]:
        return {"name": self.name, "path": self.path, "kind": self.kind}


@dataclass(frozen=True, slots=True)
class ConformanceRegressionMatrixReport:
    case_count: int
    passed_count: int
    failed_count: int
    error_count: int
    warning_count: int
    results: tuple[ConformanceRegressionResult, ...]
    report_hash: str
    ok: bool
    matrix_name: str = "data_contract_conformance"

    def as_mapping(self, *, include_report_hash: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "kind": CONFORMANCE_REGRESSION_KIND,
            "format_version": CONFORMANCE_REGRESSION_FORMAT_VERSION,
            "matrix_name": self.matrix_name,
            "ok": self.ok,
            "case_count": self.case_count,
            "passed_count": self.passed_count,
            "failed_count": self.failed_count,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "results": [item.as_mapping() for item in self.results],
        }
        if include_report_hash:
            payload["report_hash"] = self.report_hash
        return payload


def default_conformance_regression_artifacts() -> tuple[
    ConformanceRegressionArtifact, ...
]:
    return (
        ConformanceRegressionArtifact(
            name="report",
            path=CONFORMANCE_REGRESSION_REPORT_ARTIFACT_NAME,
        ),
        ConformanceRegressionArtifact(
            name="actuals",
            path=CONFORMANCE_REGRESSION_ACTUALS_ARTIFACT_NAME,
        ),
    )
