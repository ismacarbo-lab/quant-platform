"""Typed experiment usability and research-report shapes. Not a strategy."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from quant_platform.backtest.observation_reports import (
    ObservationKindSummary,
    ObservationSeveritySummary,
)

EXPERIMENT_USABILITY_KIND = "backtest_experiment_usability"
EXPERIMENT_USABILITY_FORMAT_VERSION = 1
EXPERIMENT_RESEARCH_REPORT_KIND = "backtest_experiment_research_report"
EXPERIMENT_RESEARCH_REPORT_FORMAT_VERSION = 1
EXPERIMENT_REPORT_HASH_KIND = "backtest_experiment_research_report"
EXPERIMENT_REPORT_HASH_FORMAT_VERSION = 1


class ExperimentUsabilitySeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ExperimentUsabilityCode(StrEnum):
    EXPERIMENT_MISSING = "experiment_missing"
    EXPERIMENT_ARTIFACT_MISSING = "experiment_artifact_missing"
    EXPERIMENT_HASH_MISMATCH = "experiment_hash_mismatch"
    MEMBER_BACKTEST_MISSING = "member_backtest_missing"
    MEMBER_NOT_USABLE = "member_not_usable"
    MEMBER_ARTIFACT_INVALID = "member_artifact_invalid"
    POLICY_OUTPUT_INVALID = "policy_output_invalid"
    FORBIDDEN_OPERATIONAL_LANGUAGE = "forbidden_operational_language"
    INCONSISTENT_POLICY_NAME = "inconsistent_policy_name"
    INCONSISTENT_MEMBER_COUNT = "inconsistent_member_count"
    CONSTRUCT_DETECTED = "construct_detected"
    NO_USABLE_MEMBERS = "no_usable_members"
    APP_MODE_NOT_RESEARCH = "app_mode_not_research"
    INVALID_HASH = "invalid_hash"


@dataclass(frozen=True, slots=True)
class BacktestExperimentUsabilityIssue:
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
class BacktestExperimentMemberUsability:
    replay_id: str
    backtest_id: str
    relative_path: str
    policy_name: str
    usable_result: bool
    warning_count: int
    error_count: int
    policy_output_ok: bool
    artifacts_ok: bool

    def as_mapping(self) -> dict[str, object]:
        return {
            "replay_id": self.replay_id,
            "backtest_id": self.backtest_id,
            "relative_path": self.relative_path,
            "policy_name": self.policy_name,
            "usable_result": self.usable_result,
            "warning_count": self.warning_count,
            "error_count": self.error_count,
            "policy_output_ok": self.policy_output_ok,
            "artifacts_ok": self.artifacts_ok,
        }

    def hash_mapping(self) -> dict[str, object]:
        return {
            "replay_id": self.replay_id,
            "backtest_id": self.backtest_id,
            "policy_name": self.policy_name,
            "usable_result": self.usable_result,
            "warning_count": self.warning_count,
            "error_count": self.error_count,
            "policy_output_ok": self.policy_output_ok,
            "artifacts_ok": self.artifacts_ok,
        }


@dataclass(frozen=True, slots=True)
class BacktestExperimentUsabilityGate:
    experiment_usable: bool
    research_mode: bool
    catalog_ok: bool
    artifacts_ok: bool
    experiment_hash_valid: bool
    manifest_hash_valid: bool
    members_ok: bool
    policy_output_ok: bool
    constructs_ok: bool
    error_count: int
    warning_count: int

    def as_mapping(self) -> dict[str, object]:
        return {
            "experiment_usable": self.experiment_usable,
            "research_mode": self.research_mode,
            "catalog_ok": self.catalog_ok,
            "artifacts_ok": self.artifacts_ok,
            "experiment_hash_valid": self.experiment_hash_valid,
            "manifest_hash_valid": self.manifest_hash_valid,
            "members_ok": self.members_ok,
            "policy_output_ok": self.policy_output_ok,
            "constructs_ok": self.constructs_ok,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
        }


@dataclass(frozen=True, slots=True)
class BacktestExperimentUsabilityReport:
    experiment_id: str
    experiment_usable: bool
    gate: BacktestExperimentUsabilityGate
    experiment_name: str | None
    policy_name: str | None
    experiment_hash: str | None
    manifest_hash: str | None
    member_count: int
    usable_count: int
    error_count: int
    warning_count: int
    info_count: int
    issues: tuple[BacktestExperimentUsabilityIssue, ...]
    members: tuple[BacktestExperimentMemberUsability, ...]
    experiment_root: str | None

    def as_mapping(self) -> dict[str, object]:
        return {
            "kind": EXPERIMENT_USABILITY_KIND,
            "format_version": EXPERIMENT_USABILITY_FORMAT_VERSION,
            "experiment_id": self.experiment_id,
            "experiment_usable": self.experiment_usable,
            "gate": self.gate.as_mapping(),
            "experiment_name": self.experiment_name,
            "policy_name": self.policy_name,
            "experiment_hash": self.experiment_hash,
            "manifest_hash": self.manifest_hash,
            "member_count": self.member_count,
            "usable_count": self.usable_count,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "info_count": self.info_count,
            "issues": [item.as_mapping() for item in self.issues],
            "members": [item.as_mapping() for item in self.members],
            "experiment_root": self.experiment_root,
        }


@dataclass(frozen=True, slots=True)
class BacktestExperimentObservationAggregate:
    observation_count: int
    warning_count: int
    error_count: int
    unknown_event_count: int
    correction_count: int
    corporate_action_count: int
    session_count: int
    kinds: tuple[ObservationKindSummary, ...]
    severities: tuple[ObservationSeveritySummary, ...]

    def as_mapping(self) -> dict[str, object]:
        return {
            "observation_count": self.observation_count,
            "warning_count": self.warning_count,
            "error_count": self.error_count,
            "unknown_event_count": self.unknown_event_count,
            "correction_count": self.correction_count,
            "corporate_action_count": self.corporate_action_count,
            "session_count": self.session_count,
            "kinds": [item.as_mapping() for item in self.kinds],
            "severities": [item.as_mapping() for item in self.severities],
        }


@dataclass(frozen=True, slots=True)
class BacktestExperimentMemberComparisonSummary:
    distinct_replay_id_count: int
    distinct_stream_hash_count: int
    distinct_backtest_hash_count: int
    distinct_policy_config_count: int
    same_policy_name: bool
    same_stream_hash: bool
    same_backtest_hash: bool

    def as_mapping(self) -> dict[str, object]:
        return {
            "distinct_replay_id_count": self.distinct_replay_id_count,
            "distinct_stream_hash_count": self.distinct_stream_hash_count,
            "distinct_backtest_hash_count": self.distinct_backtest_hash_count,
            "distinct_policy_config_count": self.distinct_policy_config_count,
            "same_policy_name": self.same_policy_name,
            "same_stream_hash": self.same_stream_hash,
            "same_backtest_hash": self.same_backtest_hash,
        }


@dataclass(frozen=True, slots=True)
class BacktestExperimentResearchMember:
    replay_id: str
    backtest_id: str
    stream_hash: str
    backtest_hash: str
    policy_name: str
    policy_config: dict[str, object]
    usable_result: bool
    warning_count: int
    error_count: int

    def as_mapping(self) -> dict[str, object]:
        return {
            "replay_id": self.replay_id,
            "backtest_id": self.backtest_id,
            "stream_hash": self.stream_hash,
            "backtest_hash": self.backtest_hash,
            "policy_name": self.policy_name,
            "policy_config": dict(self.policy_config),
            "usable_result": self.usable_result,
            "warning_count": self.warning_count,
            "error_count": self.error_count,
        }


@dataclass(frozen=True, slots=True)
class BacktestExperimentResearchReport:
    experiment_id: str
    experiment_name: str
    policy_name: str
    member_count: int
    usable_count: int
    warning_count: int
    error_count: int
    policy_configs: tuple[dict[str, object], ...]
    replay_ids: tuple[str, ...]
    stream_hashes: tuple[str, ...]
    backtest_hashes: tuple[str, ...]
    observations: BacktestExperimentObservationAggregate
    comparison: BacktestExperimentMemberComparisonSummary
    members: tuple[BacktestExperimentResearchMember, ...]
    experiment_hash: str
    report_hash: str

    def as_mapping(self, *, include_report_hash: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "kind": EXPERIMENT_RESEARCH_REPORT_KIND,
            "format_version": EXPERIMENT_RESEARCH_REPORT_FORMAT_VERSION,
            "experiment_id": self.experiment_id,
            "experiment_name": self.experiment_name,
            "policy_name": self.policy_name,
            "member_count": self.member_count,
            "usable_count": self.usable_count,
            "warning_count": self.warning_count,
            "error_count": self.error_count,
            "policy_configs": [dict(item) for item in self.policy_configs],
            "replay_ids": list(self.replay_ids),
            "stream_hashes": list(self.stream_hashes),
            "backtest_hashes": list(self.backtest_hashes),
            "observations": self.observations.as_mapping(),
            "comparison": self.comparison.as_mapping(),
            "members": [item.as_mapping() for item in self.members],
            "experiment_hash": self.experiment_hash,
        }
        if include_report_hash:
            payload["report_hash"] = self.report_hash
        return payload
