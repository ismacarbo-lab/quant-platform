"""Typed backtest artifact integrity reports. Not a strategy or PnL check."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class BacktestIntegritySeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class BacktestIntegrityCode(StrEnum):
    MISSING_MANIFEST = "missing_manifest"
    MISSING_SUMMARY = "missing_summary"
    MISSING_RUN_DIR = "missing_run_dir"
    ABSOLUTE_PATH = "absolute_path"
    PATH_ESCAPE = "path_escape"
    INVALID_HASH = "invalid_hash"
    MANIFEST_HASH_MISMATCH = "manifest_hash_mismatch"
    BACKTEST_HASH_MISMATCH = "backtest_hash_mismatch"
    POLICY_OUTPUT_HASH_MISMATCH = "policy_output_hash_mismatch"
    SECRET_LIKE_VALUE = "secret_like_value"  # noqa: S105
    COUNT_MISMATCH = "count_mismatch"
    UNSUPPORTED_POLICY = "unsupported_policy"
    CATALOG_MANIFEST_MISMATCH = "catalog_manifest_mismatch"
    CATALOG_ENTRY_MISSING = "catalog_entry_missing"
    INVALID_JSON = "invalid_json"
    EMPTY_ARTIFACT_PATH = "empty_artifact_path"
    MISSING_ARTIFACT = "missing_artifact"


SEVERITY_RANK: dict[str, int] = {
    BacktestIntegritySeverity.ERROR.value: 0,
    BacktestIntegritySeverity.WARNING.value: 1,
    BacktestIntegritySeverity.INFO.value: 2,
}

INTEGRITY_KIND = "backtest_artifact_verification"
INTEGRITY_FORMAT_VERSION = 1
CATALOG_INTEGRITY_KIND = "backtest_catalog_verification"
CATALOG_INTEGRITY_FORMAT_VERSION = 1


@dataclass(frozen=True, slots=True)
class BacktestArtifactVerificationRequest:
    run_root: Path
    expected_backtest_id: str | None = None


@dataclass(frozen=True, slots=True)
class BacktestArtifactVerificationIssue:
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
class BacktestArtifactStatus:
    name: str
    path: str
    exists: bool
    relative: bool
    escaped: bool

    def as_mapping(self) -> dict[str, object]:
        return {
            "name": self.name,
            "path": self.path,
            "exists": self.exists,
            "relative": self.relative,
            "escaped": self.escaped,
        }


@dataclass(frozen=True, slots=True)
class BacktestArtifactVerificationReport:
    run_root: str
    backtest_id: str | None
    replay_id: str | None
    ok: bool
    error_count: int
    warning_count: int
    info_count: int
    issues: tuple[BacktestArtifactVerificationIssue, ...]
    artifacts: tuple[BacktestArtifactStatus, ...]
    stream_hash: str | None
    backtest_hash: str | None
    recomputed_backtest_hash: str | None
    manifest_hash: str | None
    recomputed_manifest_hash: str | None
    policy_name: str | None
    event_count: int | None
    policy_output_hash: str | None

    def as_mapping(self) -> dict[str, object]:
        return {
            "kind": INTEGRITY_KIND,
            "format_version": INTEGRITY_FORMAT_VERSION,
            "run_root": self.run_root,
            "backtest_id": self.backtest_id,
            "replay_id": self.replay_id,
            "ok": self.ok,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "info_count": self.info_count,
            "issues": [item.as_mapping() for item in self.issues],
            "artifacts": [item.as_mapping() for item in self.artifacts],
            "stream_hash": self.stream_hash,
            "backtest_hash": self.backtest_hash,
            "recomputed_backtest_hash": self.recomputed_backtest_hash,
            "manifest_hash": self.manifest_hash,
            "recomputed_manifest_hash": self.recomputed_manifest_hash,
            "policy_name": self.policy_name,
            "event_count": self.event_count,
            "policy_output_hash": self.policy_output_hash,
        }


@dataclass(frozen=True, slots=True)
class BacktestCatalogIntegrityReport:
    base_dir: str
    entry_count: int
    verified_count: int
    error_count: int
    warning_count: int
    ok: bool
    reports: tuple[BacktestArtifactVerificationReport, ...]

    def as_mapping(self) -> dict[str, object]:
        return {
            "kind": CATALOG_INTEGRITY_KIND,
            "format_version": CATALOG_INTEGRITY_FORMAT_VERSION,
            "base_dir": self.base_dir,
            "entry_count": self.entry_count,
            "verified_count": self.verified_count,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "ok": self.ok,
            "reports": [item.as_mapping() for item in self.reports],
        }
