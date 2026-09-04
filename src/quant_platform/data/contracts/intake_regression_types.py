"""Typed contract-payload intake regression shapes. Not a PnL check."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

INTAKE_REGRESSION_KIND = "contract_payload_intake_regression_report"
INTAKE_REGRESSION_FORMAT_VERSION = 1
INTAKE_REGRESSION_HASH_KIND = "contract_payload_intake_regression_report"
INTAKE_REGRESSION_HASH_FORMAT_VERSION = 1
INTAKE_REGRESSION_ACTUALS_KIND = "contract_payload_intake_regression_actuals"
INTAKE_REGRESSION_ACTUALS_FORMAT_VERSION = 1

INTAKE_REGRESSION_REPORT_ARTIFACT_NAME = (
    "contract_payload_intake_regression_report.json"
)
INTAKE_REGRESSION_ACTUALS_ARTIFACT_NAME = (
    "contract_payload_intake_regression_actuals.json"
)

BATCH_FIXTURE_NAME = "batch.json"
REQUEST_FIXTURE_NAME = "request.json"
EXPECTED_FIXTURE_NAME = "expected.json"


class IntakeRegressionSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class IntakeRegressionCode(StrEnum):
    MISSING_FIXTURE = "missing_fixture"
    INVALID_FIXTURE = "invalid_fixture"
    INTAKE_HASH_CHANGED = "intake_hash_changed"
    BATCH_HASH_CHANGED = "batch_hash_changed"
    CONFORMANCE_HASH_CHANGED = "conformance_hash_changed"
    ISSUE_COUNT_CHANGED = "issue_count_changed"
    ISSUE_CODES_CHANGED = "issue_codes_changed"
    COUNT_CHANGED = "count_changed"
    FORBIDDEN_METRIC_DETECTED = "forbidden_metric_detected"
    UNEXPECTED_ERROR = "unexpected_error"


EXPECTED_DRIFT_CODES = frozenset(
    {
        IntakeRegressionCode.INTAKE_HASH_CHANGED.value,
        IntakeRegressionCode.BATCH_HASH_CHANGED.value,
        IntakeRegressionCode.CONFORMANCE_HASH_CHANGED.value,
        IntakeRegressionCode.ISSUE_COUNT_CHANGED.value,
        IntakeRegressionCode.ISSUE_CODES_CHANGED.value,
        IntakeRegressionCode.COUNT_CHANGED.value,
    }
)


@dataclass(frozen=True, slots=True)
class IntakeRegressionExpected:
    intake_hash: str | None = None
    batch_hash: str | None = None
    conformance_hash: str | None = None
    issue_count: int | None = None
    issue_codes: tuple[str, ...] | None = None
    ok: bool | None = None
    write_db: bool | None = None
    allow_invalid: bool | None = None
    planned_daily_bar_count: int | None = None
    planned_corporate_action_count: int | None = None
    planned_market_session_count: int | None = None

    def as_mapping(self) -> dict[str, object]:
        return {
            "expected_intake_hash": self.intake_hash,
            "expected_batch_hash": self.batch_hash,
            "expected_conformance_hash": self.conformance_hash,
            "expected_issue_count": self.issue_count,
            "expected_issue_codes": (
                None if self.issue_codes is None else list(self.issue_codes)
            ),
            "expected_ok": self.ok,
            "expected_write_db": self.write_db,
            "expected_allow_invalid": self.allow_invalid,
            "expected_planned_daily_bar_count": self.planned_daily_bar_count,
            "expected_planned_corporate_action_count": (
                self.planned_corporate_action_count
            ),
            "expected_planned_market_session_count": (
                self.planned_market_session_count
            ),
        }


@dataclass(frozen=True, slots=True)
class IntakeRegressionCase:
    case_id: str
    fixture_dir: str
    expected: IntakeRegressionExpected

    def as_mapping(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "case_id": self.case_id,
            "fixture_dir": self.fixture_dir,
        }
        payload.update(self.expected.as_mapping())
        return payload


@dataclass(frozen=True, slots=True)
class IntakeRegressionActual:
    case_id: str
    intake_hash: str | None
    batch_hash: str | None
    conformance_hash: str | None
    issue_count: int | None
    issue_codes: tuple[str, ...]
    ok: bool | None
    write_db: bool | None
    allow_invalid: bool | None
    planned_daily_bar_count: int | None
    planned_corporate_action_count: int | None
    planned_market_session_count: int | None

    def as_mapping(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "intake_hash": self.intake_hash,
            "batch_hash": self.batch_hash,
            "conformance_hash": self.conformance_hash,
            "issue_count": self.issue_count,
            "issue_codes": list(self.issue_codes),
            "ok": self.ok,
            "write_db": self.write_db,
            "allow_invalid": self.allow_invalid,
            "planned_daily_bar_count": self.planned_daily_bar_count,
            "planned_corporate_action_count": self.planned_corporate_action_count,
            "planned_market_session_count": self.planned_market_session_count,
        }


@dataclass(frozen=True, slots=True)
class IntakeRegressionIssue:
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
class IntakeRegressionResult:
    case_id: str
    fixture_dir: str
    passed: bool
    actual: IntakeRegressionActual | None
    expected: IntakeRegressionExpected
    issues: tuple[IntakeRegressionIssue, ...]

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
class IntakeRegressionArtifact:
    name: str
    path: str
    kind: str = "json"

    def as_mapping(self) -> dict[str, object]:
        return {"name": self.name, "path": self.path, "kind": self.kind}


@dataclass(frozen=True, slots=True)
class IntakeRegressionMatrixReport:
    case_count: int
    passed_count: int
    failed_count: int
    error_count: int
    warning_count: int
    results: tuple[IntakeRegressionResult, ...]
    report_hash: str
    ok: bool
    matrix_name: str = "contract_payload_intake"

    def as_mapping(self, *, include_report_hash: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "kind": INTAKE_REGRESSION_KIND,
            "format_version": INTAKE_REGRESSION_FORMAT_VERSION,
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


def default_intake_regression_artifacts() -> tuple[IntakeRegressionArtifact, ...]:
    return (
        IntakeRegressionArtifact(
            name="report",
            path=INTAKE_REGRESSION_REPORT_ARTIFACT_NAME,
        ),
        IntakeRegressionArtifact(
            name="actuals",
            path=INTAKE_REGRESSION_ACTUALS_ARTIFACT_NAME,
        ),
    )
