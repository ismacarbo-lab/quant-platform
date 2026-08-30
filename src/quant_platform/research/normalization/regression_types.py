"""Typed corporate-action normalization regression shapes. Not a PnL check."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

NORMALIZATION_REGRESSION_KIND = "normalization_regression_matrix_report"
NORMALIZATION_REGRESSION_FORMAT_VERSION = 1
NORMALIZATION_REGRESSION_HASH_KIND = "normalization_regression_matrix_report"
NORMALIZATION_REGRESSION_HASH_FORMAT_VERSION = 1
NORMALIZATION_REGRESSION_ACTUALS_KIND = "normalization_regression_actuals"
NORMALIZATION_REGRESSION_ACTUALS_FORMAT_VERSION = 1

NORMALIZATION_REGRESSION_REPORT_ARTIFACT_NAME = "normalization_regression_report.json"
NORMALIZATION_REGRESSION_ACTUALS_ARTIFACT_NAME = "normalization_regression_actuals.json"

BARS_FIXTURE_NAME = "daily_bars.csv"
ACTIONS_FIXTURE_NAME = "corporate_actions.csv"
REQUEST_FIXTURE_NAME = "request.json"
EXPECTED_FIXTURE_NAME = "expected.json"


class NormalizationRegressionSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class NormalizationRegressionCode(StrEnum):
    MISSING_FIXTURE = "missing_fixture"
    INVALID_REQUEST = "invalid_request"
    DATASET_HASH_CHANGED = "dataset_hash_changed"
    BAR_COUNT_CHANGED = "bar_count_changed"
    ISSUE_COUNT_CHANGED = "issue_count_changed"
    ADJUSTED_BAR_COUNT_CHANGED = "adjusted_bar_count_changed"
    ACTIONS_APPLIED_CHANGED = "actions_applied_changed"
    WARNING_COUNT_CHANGED = "warning_count_changed"
    FORBIDDEN_METRIC_DETECTED = "forbidden_metric_detected"
    UNEXPECTED_ERROR = "unexpected_error"


NORMALIZATION_REGRESSION_SEVERITY_RANK: dict[str, int] = {
    NormalizationRegressionSeverity.ERROR.value: 0,
    NormalizationRegressionSeverity.WARNING.value: 1,
    NormalizationRegressionSeverity.INFO.value: 2,
}

EXPECTED_DRIFT_CODES = frozenset(
    {
        NormalizationRegressionCode.DATASET_HASH_CHANGED.value,
        NormalizationRegressionCode.BAR_COUNT_CHANGED.value,
        NormalizationRegressionCode.ISSUE_COUNT_CHANGED.value,
        NormalizationRegressionCode.ADJUSTED_BAR_COUNT_CHANGED.value,
        NormalizationRegressionCode.ACTIONS_APPLIED_CHANGED.value,
        NormalizationRegressionCode.WARNING_COUNT_CHANGED.value,
    }
)


@dataclass(frozen=True, slots=True)
class NormalizationRegressionExpected:
    dataset_hash: str | None = None
    bar_count: int | None = None
    issue_count: int | None = None
    adjusted_bar_count: int | None = None
    actions_applied: int | None = None
    warnings: tuple[str, ...] | None = None

    def as_mapping(self) -> dict[str, object]:
        return {
            "expected_dataset_hash": self.dataset_hash,
            "expected_bar_count": self.bar_count,
            "expected_issue_count": self.issue_count,
            "expected_adjusted_bar_count": self.adjusted_bar_count,
            "expected_actions_applied": self.actions_applied,
            "expected_warnings": None if self.warnings is None else list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class NormalizationRegressionCase:
    case_id: str
    fixture_dir: str
    adjustment_mode: str
    as_of: datetime | None
    expected: NormalizationRegressionExpected

    def as_mapping(self) -> dict[str, object]:
        from quant_platform.research.snapshots import canonical_datetime

        payload: dict[str, object] = {
            "case_id": self.case_id,
            "fixture_dir": self.fixture_dir,
            "adjustment_mode": self.adjustment_mode,
            "as_of": None if self.as_of is None else canonical_datetime(self.as_of),
        }
        payload.update(self.expected.as_mapping())
        return payload


@dataclass(frozen=True, slots=True)
class NormalizationRegressionActual:
    case_id: str
    adjustment_mode: str
    as_of: datetime | None
    dataset_hash: str | None
    bar_count: int | None
    issue_count: int | None
    adjusted_bar_count: int | None
    actions_applied: int | None
    warnings: tuple[str, ...]
    raw_dataset_hash: str | None = None

    def as_mapping(self) -> dict[str, object]:
        from quant_platform.research.snapshots import canonical_datetime

        return {
            "case_id": self.case_id,
            "adjustment_mode": self.adjustment_mode,
            "as_of": None if self.as_of is None else canonical_datetime(self.as_of),
            "dataset_hash": self.dataset_hash,
            "bar_count": self.bar_count,
            "issue_count": self.issue_count,
            "adjusted_bar_count": self.adjusted_bar_count,
            "actions_applied": self.actions_applied,
            "warnings": list(self.warnings),
            "raw_dataset_hash": self.raw_dataset_hash,
        }


@dataclass(frozen=True, slots=True)
class NormalizationRegressionIssue:
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
class NormalizationRegressionResult:
    case_id: str
    fixture_dir: str
    adjustment_mode: str
    as_of: datetime | None
    passed: bool
    actual: NormalizationRegressionActual | None
    expected: NormalizationRegressionExpected
    issues: tuple[NormalizationRegressionIssue, ...]

    def as_mapping(self) -> dict[str, object]:
        from quant_platform.research.snapshots import canonical_datetime

        return {
            "case_id": self.case_id,
            "fixture_dir": self.fixture_dir,
            "adjustment_mode": self.adjustment_mode,
            "as_of": None if self.as_of is None else canonical_datetime(self.as_of),
            "passed": self.passed,
            "actual": None if self.actual is None else self.actual.as_mapping(),
            "expected": self.expected.as_mapping(),
            "issues": [item.as_mapping() for item in self.issues],
        }


@dataclass(frozen=True, slots=True)
class NormalizationRegressionArtifact:
    name: str
    path: str
    kind: str = "json"

    def as_mapping(self) -> dict[str, object]:
        return {"name": self.name, "path": self.path, "kind": self.kind}


@dataclass(frozen=True, slots=True)
class NormalizationRegressionMatrixReport:
    case_count: int
    passed_count: int
    failed_count: int
    error_count: int
    warning_count: int
    results: tuple[NormalizationRegressionResult, ...]
    report_hash: str
    ok: bool
    matrix_name: str = "normalization_regression"

    def as_mapping(self, *, include_report_hash: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "kind": NORMALIZATION_REGRESSION_KIND,
            "format_version": NORMALIZATION_REGRESSION_FORMAT_VERSION,
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


def default_normalization_regression_artifacts() -> tuple[
    NormalizationRegressionArtifact, ...
]:
    return (
        NormalizationRegressionArtifact(
            name="report",
            path=NORMALIZATION_REGRESSION_REPORT_ARTIFACT_NAME,
        ),
        NormalizationRegressionArtifact(
            name="actuals",
            path=NORMALIZATION_REGRESSION_ACTUALS_ARTIFACT_NAME,
        ),
    )
