"""Typed policy-output integrity reports. Not a strategy or PnL check."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

POLICY_OUTPUT_INTEGRITY_KIND = "policy_output_verification"
POLICY_OUTPUT_INTEGRITY_FORMAT_VERSION = 1
POLICY_OUTPUT_COMPARISON_KIND = "policy_output_comparison"
POLICY_OUTPUT_COMPARISON_FORMAT_VERSION = 1


class PolicyOutputIntegritySeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class PolicyOutputStatus(StrEnum):
    OK = "ok"
    INVALID = "invalid"


class PolicyOutputComparisonVerdict(StrEnum):
    IDENTICAL = "identical"
    SAME_COUNTS = "same_counts"
    DIFFERENT = "different"


class PolicyOutputIntegrityCode(StrEnum):
    MISSING_POLICY_OUTPUT = "missing_policy_output"
    INVALID_POLICY_OUTPUT_JSON = "invalid_policy_output_json"
    POLICY_OUTPUT_HASH_MISMATCH = "policy_output_hash_mismatch"
    FORBIDDEN_OPERATIONAL_LANGUAGE = "forbidden_operational_language"
    INVALID_OBSERVATION_KIND = "invalid_observation_kind"
    INVALID_OBSERVATION_SEVERITY = "invalid_observation_severity"
    SECRET_LIKE_VALUE = "secret_like_value"  # noqa: S105
    TIMESTAMP_NOT_UTC = "timestamp_not_utc"
    COUNT_MISMATCH = "count_mismatch"
    ABSOLUTE_PATH = "absolute_path"
    PATH_ESCAPE = "path_escape"
    INVALID_HASH = "invalid_hash"


POLICY_OUTPUT_SEVERITY_RANK: dict[str, int] = {
    PolicyOutputIntegritySeverity.ERROR.value: 0,
    PolicyOutputIntegritySeverity.WARNING.value: 1,
    PolicyOutputIntegritySeverity.INFO.value: 2,
}


@dataclass(frozen=True, slots=True)
class PolicyOutputVerificationIssue:
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
class PolicyOutputVerificationReport:
    run_root: str
    ok: bool
    status: str
    error_count: int
    warning_count: int
    info_count: int
    issues: tuple[PolicyOutputVerificationIssue, ...]
    policy_name: str | None
    stored_hash: str | None
    recomputed_hash: str | None
    observation_count: int | None

    def as_mapping(self) -> dict[str, object]:
        return {
            "kind": POLICY_OUTPUT_INTEGRITY_KIND,
            "format_version": POLICY_OUTPUT_INTEGRITY_FORMAT_VERSION,
            "run_root": self.run_root,
            "ok": self.ok,
            "status": self.status,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "info_count": self.info_count,
            "issues": [item.as_mapping() for item in self.issues],
            "policy_name": self.policy_name,
            "stored_hash": self.stored_hash,
            "recomputed_hash": self.recomputed_hash,
            "observation_count": self.observation_count,
        }


@dataclass(frozen=True, slots=True)
class PolicyOutputComparisonItem:
    field: str
    left: str | None
    right: str | None

    def as_mapping(self) -> dict[str, object]:
        return {"field": self.field, "left": self.left, "right": self.right}


@dataclass(frozen=True, slots=True)
class PolicyOutputComparison:
    verdict: str
    identical: bool
    same_policy_output_hash: bool
    same_observation_count: bool
    same_counts_by_kind: bool
    same_counts_by_severity: bool
    same_warning_count: bool
    same_error_count: bool
    same_policy_name: bool
    same_policy_config: bool
    same_first_observation_time: bool
    same_last_observation_time: bool
    left_hash: str | None
    right_hash: str | None
    items: tuple[PolicyOutputComparisonItem, ...]

    def as_mapping(self) -> dict[str, object]:
        return {
            "kind": POLICY_OUTPUT_COMPARISON_KIND,
            "format_version": POLICY_OUTPUT_COMPARISON_FORMAT_VERSION,
            "verdict": self.verdict,
            "identical": self.identical,
            "same_policy_output_hash": self.same_policy_output_hash,
            "same_observation_count": self.same_observation_count,
            "same_counts_by_kind": self.same_counts_by_kind,
            "same_counts_by_severity": self.same_counts_by_severity,
            "same_warning_count": self.same_warning_count,
            "same_error_count": self.same_error_count,
            "same_policy_name": self.same_policy_name,
            "same_policy_config": self.same_policy_config,
            "same_first_observation_time": self.same_first_observation_time,
            "same_last_observation_time": self.same_last_observation_time,
            "left_hash": self.left_hash,
            "right_hash": self.right_hash,
            "items": [item.as_mapping() for item in self.items],
        }
