"""Replay-run comparison and backtest-readiness types. Not a backtester."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from quant_platform.simulation.run_integrity import ReplayRunArtifactStatus

READINESS_KIND = "replay_run_readiness"
READINESS_FORMAT_VERSION = 1
DIFF_KIND = "replay_run_diff"
DIFF_FORMAT_VERSION = 1

SEVERITY_RANK: dict[str, int] = {"error": 0, "warning": 1, "info": 2}


class ReplayRunReadinessSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ReplayRunReadinessCode(StrEnum):
    STREAM_HASH_DIFF = "stream_hash_diff"
    MANIFEST_HASH_DIFF = "manifest_hash_diff"
    EVENT_COUNT_DIFF = "event_count_diff"
    BOUNDARY_NOT_OK = "boundary_not_ok"
    AUDIT_ERRORS_PRESENT = "audit_errors_present"
    ARTIFACT_MISSING = "artifact_missing"
    ARTIFACT_HASH_MISMATCH = "artifact_hash_mismatch"
    NOT_REPRODUCIBLE = "not_reproducible"
    NOT_USABLE = "not_usable"
    SNAPSHOT_NOT_VERIFIED = "snapshot_not_verified"
    TRADING_CONSTRUCT_DETECTED = "trading_construct_detected"
    MISSING_DATASET_SNAPSHOT_LINK = "missing_dataset_snapshot_link"
    DIRTY_GIT_STATE_UNKNOWN = "dirty_git_state_unknown"
    CATALOG_ENTRY_MISSING = "catalog_entry_missing"
    APP_MODE_NOT_RESEARCH = "app_mode_not_research"
    INVALID_HASH = "invalid_hash"


class ReplayRunDiffVerdict(StrEnum):
    IDENTICAL = "identical"
    SAME_STREAM = "same_stream"
    DIFFERENT = "different"


@dataclass(frozen=True, slots=True)
class ReplayRunDiffItem:
    field: str
    code: str
    left: str | None
    right: str | None

    def as_mapping(self) -> dict[str, object]:
        return {
            "field": self.field,
            "code": self.code,
            "left": self.left,
            "right": self.right,
        }


@dataclass(frozen=True, slots=True)
class ReplayRunDiff:
    replay_a_id: str
    replay_b_id: str
    same_stream_hash: bool
    same_manifest_hash: bool
    identical: bool
    verdict: str
    items: tuple[ReplayRunDiffItem, ...]

    def as_mapping(self) -> dict[str, object]:
        return {
            "kind": DIFF_KIND,
            "format_version": DIFF_FORMAT_VERSION,
            "replay_a_id": self.replay_a_id,
            "replay_b_id": self.replay_b_id,
            "same_stream_hash": self.same_stream_hash,
            "same_manifest_hash": self.same_manifest_hash,
            "identical": self.identical,
            "verdict": self.verdict,
            "items": [item.as_mapping() for item in self.items],
        }


@dataclass(frozen=True, slots=True)
class ReplayRunReadinessIssue:
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
class BacktestReadinessGate:
    ready_for_backtest: bool
    research_mode: bool
    error_count: int
    warning_count: int
    boundary_ok: bool
    is_reproducible: bool
    is_usable: bool
    artifacts_ok: bool
    stream_hash_valid: bool
    trading_constructs_ok: bool

    def as_mapping(self) -> dict[str, object]:
        return {
            "ready_for_backtest": self.ready_for_backtest,
            "research_mode": self.research_mode,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "boundary_ok": self.boundary_ok,
            "is_reproducible": self.is_reproducible,
            "is_usable": self.is_usable,
            "artifacts_ok": self.artifacts_ok,
            "stream_hash_valid": self.stream_hash_valid,
            "trading_constructs_ok": self.trading_constructs_ok,
        }


@dataclass(frozen=True, slots=True)
class ReplayRunReadinessReport:
    replay_id: str
    ready_for_backtest: bool
    gate: BacktestReadinessGate
    stream_hash: str | None
    manifest_hash: str | None
    boundary_ok: bool | None
    error_count: int
    warning_count: int
    info_count: int
    issues: tuple[ReplayRunReadinessIssue, ...]
    artifacts: tuple[ReplayRunArtifactStatus, ...]
    run_root: str | None

    def as_mapping(self) -> dict[str, object]:
        return {
            "kind": READINESS_KIND,
            "format_version": READINESS_FORMAT_VERSION,
            "replay_id": self.replay_id,
            "ready_for_backtest": self.ready_for_backtest,
            "gate": self.gate.as_mapping(),
            "stream_hash": self.stream_hash,
            "manifest_hash": self.manifest_hash,
            "boundary_ok": self.boundary_ok,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "info_count": self.info_count,
            "issues": [item.as_mapping() for item in self.issues],
            "artifacts": [item.as_mapping() for item in self.artifacts],
            "run_root": self.run_root,
        }


@dataclass(frozen=True, slots=True)
class TradingConstructFinding:
    kind: str
    name: str
    code: str
    message: str

    def as_mapping(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "name": self.name,
            "code": self.code,
            "message": self.message,
        }
