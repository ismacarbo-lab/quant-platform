"""Typed research-policy regression matrix shapes. Not a strategy or PnL check."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

POLICY_REGRESSION_KIND = "policy_regression_matrix_report"
POLICY_REGRESSION_FORMAT_VERSION = 1
POLICY_REGRESSION_HASH_KIND = "policy_regression_matrix_report"
POLICY_REGRESSION_HASH_FORMAT_VERSION = 1
POLICY_REGRESSION_ACTUALS_KIND = "policy_regression_actuals"
POLICY_REGRESSION_ACTUALS_FORMAT_VERSION = 1
POLICY_REGRESSION_MATRIX_KIND = "policy_regression_matrix"
POLICY_REGRESSION_MATRIX_FORMAT_VERSION = 1

POLICY_REGRESSION_REPORT_ARTIFACT_NAME = "policy_regression_report.json"
POLICY_REGRESSION_ACTUALS_ARTIFACT_NAME = "policy_regression_actuals.json"


class PolicyRegressionSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class PolicyRegressionCode(StrEnum):
    MISSING_FIXTURE = "missing_fixture"
    UNKNOWN_POLICY = "unknown_policy"
    INVALID_POLICY_CONFIG = "invalid_policy_config"
    POLICY_OUTPUT_HASH_CHANGED = "policy_output_hash_changed"
    OBSERVATION_COUNT_CHANGED = "observation_count_changed"
    OBSERVATION_KIND_COUNTS_CHANGED = "observation_kind_counts_changed"
    OBSERVATION_SEVERITY_COUNTS_CHANGED = "observation_severity_counts_changed"
    FORBIDDEN_OPERATIONAL_LANGUAGE = "forbidden_operational_language"
    UNEXPECTED_ERROR = "unexpected_error"


POLICY_REGRESSION_SEVERITY_RANK: dict[str, int] = {
    PolicyRegressionSeverity.ERROR.value: 0,
    PolicyRegressionSeverity.WARNING.value: 1,
    PolicyRegressionSeverity.INFO.value: 2,
}

EXPECTED_DRIFT_CODES = frozenset(
    {
        PolicyRegressionCode.POLICY_OUTPUT_HASH_CHANGED.value,
        PolicyRegressionCode.OBSERVATION_COUNT_CHANGED.value,
        PolicyRegressionCode.OBSERVATION_KIND_COUNTS_CHANGED.value,
        PolicyRegressionCode.OBSERVATION_SEVERITY_COUNTS_CHANGED.value,
    }
)


@dataclass(frozen=True, slots=True)
class PolicyRegressionExpected:
    policy_output_hash: str | None = None
    observation_count: int | None = None
    counts_by_kind: dict[str, int] | None = None
    counts_by_severity: dict[str, int] | None = None

    def as_mapping(self) -> dict[str, object]:
        return {
            "expected_policy_output_hash": self.policy_output_hash,
            "expected_observation_count": self.observation_count,
            "expected_counts_by_kind": _optional_counts(self.counts_by_kind),
            "expected_counts_by_severity": _optional_counts(self.counts_by_severity),
        }


@dataclass(frozen=True, slots=True)
class PolicyRegressionCase:
    case_id: str
    description: str
    fixture_path: str
    policy_name: str
    policy_config: dict[str, object]
    expected: PolicyRegressionExpected

    def as_mapping(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "case_id": self.case_id,
            "description": self.description,
            "fixture_path": self.fixture_path,
            "policy_name": self.policy_name,
            "policy_config": dict(self.policy_config),
        }
        payload.update(self.expected.as_mapping())
        return payload


@dataclass(frozen=True, slots=True)
class PolicyRegressionActual:
    case_id: str
    policy_name: str
    policy_config: dict[str, object]
    policy_output_hash: str | None
    observation_count: int | None
    counts_by_kind: dict[str, int]
    counts_by_severity: dict[str, int]
    integrity_ok: bool | None = None

    def as_mapping(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "policy_name": self.policy_name,
            "policy_config": dict(self.policy_config),
            "policy_output_hash": self.policy_output_hash,
            "observation_count": self.observation_count,
            "counts_by_kind": dict(sorted(self.counts_by_kind.items())),
            "counts_by_severity": dict(sorted(self.counts_by_severity.items())),
            "integrity_ok": self.integrity_ok,
        }


@dataclass(frozen=True, slots=True)
class PolicyRegressionIssue:
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
class PolicyRegressionResult:
    case_id: str
    description: str
    fixture_path: str
    policy_name: str
    passed: bool
    actual: PolicyRegressionActual | None
    expected: PolicyRegressionExpected
    issues: tuple[PolicyRegressionIssue, ...]

    def as_mapping(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "description": self.description,
            "fixture_path": self.fixture_path,
            "policy_name": self.policy_name,
            "passed": self.passed,
            "actual": None if self.actual is None else self.actual.as_mapping(),
            "expected": self.expected.as_mapping(),
            "issues": [item.as_mapping() for item in self.issues],
        }


@dataclass(frozen=True, slots=True)
class PolicyRegressionArtifact:
    name: str
    path: str
    kind: str = "json"

    def as_mapping(self) -> dict[str, object]:
        return {"name": self.name, "path": self.path, "kind": self.kind}


@dataclass(frozen=True, slots=True)
class PolicyRegressionMatrixReport:
    case_count: int
    passed_count: int
    failed_count: int
    error_count: int
    warning_count: int
    results: tuple[PolicyRegressionResult, ...]
    report_hash: str
    ok: bool
    matrix_name: str = "matrix.json"

    def as_mapping(self, *, include_report_hash: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "kind": POLICY_REGRESSION_KIND,
            "format_version": POLICY_REGRESSION_FORMAT_VERSION,
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


def default_policy_regression_artifacts() -> tuple[PolicyRegressionArtifact, ...]:
    return (
        PolicyRegressionArtifact(
            name="report",
            path=POLICY_REGRESSION_REPORT_ARTIFACT_NAME,
        ),
        PolicyRegressionArtifact(
            name="actuals",
            path=POLICY_REGRESSION_ACTUALS_ARTIFACT_NAME,
        ),
    )


def _optional_counts(value: dict[str, int] | None) -> dict[str, int] | None:
    if value is None:
        return None
    return dict(sorted(value.items()))
