"""Usability gate for dry-run backtest results. Not a strategy or PnL check."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from sqlalchemy.orm import Session

from quant_platform.backtest.catalog import get_backtest_run_by_id
from quant_platform.backtest.integrity import (
    resolve_backtest_run_directory,
    verify_registered_backtest_run,
)
from quant_platform.backtest.integrity_types import (
    SEVERITY_RANK,
    BacktestArtifactStatus,
    BacktestArtifactVerificationIssue,
    BacktestArtifactVerificationReport,
    BacktestIntegrityCode,
)
from quant_platform.backtest.types import (
    ALLOWED_POLICY_NAMES,
    NOOP_POLICY_NAME,
    BacktestRunCatalogEntry,
)
from quant_platform.core.config import get_settings
from quant_platform.research.snapshots import is_sha256_digest
from quant_platform.simulation.run_catalog import get_replay_run_by_id

USABILITY_KIND = "backtest_result_usability"
USABILITY_FORMAT_VERSION = 1

_ARTIFACT_MISSING_CODES = frozenset(
    {
        BacktestIntegrityCode.MISSING_MANIFEST.value,
        BacktestIntegrityCode.MISSING_SUMMARY.value,
        BacktestIntegrityCode.MISSING_RUN_DIR.value,
        BacktestIntegrityCode.MISSING_ARTIFACT.value,
        BacktestIntegrityCode.EMPTY_ARTIFACT_PATH.value,
    }
)
_HASH_MISMATCH_CODES = frozenset(
    {
        BacktestIntegrityCode.MANIFEST_HASH_MISMATCH.value,
        BacktestIntegrityCode.BACKTEST_HASH_MISMATCH.value,
        BacktestIntegrityCode.CATALOG_MANIFEST_MISMATCH.value,
        BacktestIntegrityCode.COUNT_MISMATCH.value,
        BacktestIntegrityCode.POLICY_OUTPUT_HASH_MISMATCH.value,
    }
)


class BacktestUsabilitySeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class BacktestUsabilityCode(StrEnum):
    CATALOG_ENTRY_MISSING = "catalog_entry_missing"
    NOT_REPRODUCIBLE = "not_reproducible"
    NOT_USABLE = "not_usable"
    ARTIFACT_MISSING = "artifact_missing"
    ARTIFACT_HASH_MISMATCH = "artifact_hash_mismatch"
    UNSUPPORTED_POLICY = "unsupported_policy"
    INVALID_HASH = "invalid_hash"
    ERRORS_PRESENT = "errors_present"
    APP_MODE_NOT_RESEARCH = "app_mode_not_research"
    REPLAY_CATALOG_MISSING = "replay_catalog_missing"


@dataclass(frozen=True, slots=True)
class BacktestUsabilityIssue:
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
class BacktestUsabilityGate:
    usable_result: bool
    research_mode: bool
    is_reproducible: bool
    is_usable: bool
    artifacts_ok: bool
    policy_ok: bool
    backtest_hash_valid: bool
    manifest_hash_valid: bool
    replay_registered: bool
    error_count: int
    warning_count: int

    def as_mapping(self) -> dict[str, object]:
        return {
            "usable_result": self.usable_result,
            "research_mode": self.research_mode,
            "is_reproducible": self.is_reproducible,
            "is_usable": self.is_usable,
            "artifacts_ok": self.artifacts_ok,
            "policy_ok": self.policy_ok,
            "backtest_hash_valid": self.backtest_hash_valid,
            "manifest_hash_valid": self.manifest_hash_valid,
            "replay_registered": self.replay_registered,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
        }


@dataclass(frozen=True, slots=True)
class BacktestUsabilityReport:
    backtest_id: str
    usable_result: bool
    gate: BacktestUsabilityGate
    replay_id: str | None
    stream_hash: str | None
    backtest_hash: str | None
    manifest_hash: str | None
    policy_name: str | None
    error_count: int
    warning_count: int
    info_count: int
    issues: tuple[BacktestUsabilityIssue, ...]
    artifacts: tuple[BacktestArtifactStatus, ...]
    run_root: str | None

    def as_mapping(self) -> dict[str, object]:
        return {
            "kind": USABILITY_KIND,
            "format_version": USABILITY_FORMAT_VERSION,
            "backtest_id": self.backtest_id,
            "usable_result": self.usable_result,
            "gate": self.gate.as_mapping(),
            "replay_id": self.replay_id,
            "stream_hash": self.stream_hash,
            "backtest_hash": self.backtest_hash,
            "manifest_hash": self.manifest_hash,
            "policy_name": self.policy_name,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "info_count": self.info_count,
            "issues": [item.as_mapping() for item in self.issues],
            "artifacts": [item.as_mapping() for item in self.artifacts],
            "run_root": self.run_root,
        }


def evaluate_backtest_result_usability(
    session: Session,
    backtest_id: str,
    base_dir: Path | str,
    *,
    research_mode: bool | None = None,
) -> BacktestUsabilityReport:
    """Decide whether a registered NoOp backtest is usable research evidence.

    Does not imply a profitable strategy. Does not create orders or PnL.
    """
    mode = get_settings().is_research_mode if research_mode is None else research_mode
    cleaned = backtest_id.strip()
    entry = get_backtest_run_by_id(session, cleaned) if cleaned else None
    run_root = resolve_backtest_run_directory(base_dir, cleaned) if cleaned else None
    integrity: BacktestArtifactVerificationReport | None = None
    if cleaned and run_root is not None:
        integrity = verify_registered_backtest_run(session, cleaned, run_root)
    replay_registered = False
    if entry is not None:
        replay_registered = get_replay_run_by_id(session, entry.replay_id) is not None
    return build_backtest_usability_report(
        backtest_id=cleaned or backtest_id,
        entry=entry,
        integrity=integrity,
        replay_registered=replay_registered,
        research_mode=mode,
        run_root=run_root,
    )


def build_backtest_usability_report(
    *,
    backtest_id: str,
    entry: BacktestRunCatalogEntry | None,
    integrity: BacktestArtifactVerificationReport | None,
    replay_registered: bool = True,
    research_mode: bool = True,
    run_root: Path | str | None = None,
) -> BacktestUsabilityReport:
    """Pure usability evaluation. Used by tests without PostgreSQL."""
    issues: list[BacktestUsabilityIssue] = []
    if not research_mode:
        issues.append(
            _issue(
                BacktestUsabilitySeverity.ERROR,
                BacktestUsabilityCode.APP_MODE_NOT_RESEARCH,
                "APP_MODE must be research",
            )
        )
    if entry is None:
        issues.append(
            _issue(
                BacktestUsabilitySeverity.ERROR,
                BacktestUsabilityCode.CATALOG_ENTRY_MISSING,
                "backtest_id is not registered",
            )
        )
    else:
        issues.extend(_catalog_issues(entry))
        if not replay_registered:
            issues.append(
                _issue(
                    BacktestUsabilitySeverity.WARNING,
                    BacktestUsabilityCode.REPLAY_CATALOG_MISSING,
                    "replay_id is not registered in the replay catalog",
                    actual=entry.replay_id,
                )
            )
    if integrity is None:
        issues.append(
            _issue(
                BacktestUsabilitySeverity.ERROR,
                BacktestUsabilityCode.ARTIFACT_MISSING,
                "backtest run directory could not be resolved under base_dir",
                path=None if run_root is None else str(run_root),
            )
        )
    else:
        issues.extend(_integrity_issues(integrity.issues))

    ranked = _rank(issues)
    error_count = sum(
        1 for item in ranked if item.severity == BacktestUsabilitySeverity.ERROR
    )
    warning_count = sum(
        1 for item in ranked if item.severity == BacktestUsabilitySeverity.WARNING
    )
    info_count = sum(
        1 for item in ranked if item.severity == BacktestUsabilitySeverity.INFO
    )
    artifacts_ok = integrity is not None and integrity.ok
    backtest_hash = None if entry is None else entry.backtest_hash
    manifest_hash = None if entry is None else entry.manifest_hash
    policy_name = None if entry is None else entry.policy_name
    backtest_hash_valid = backtest_hash is not None and is_sha256_digest(backtest_hash)
    manifest_hash_valid = manifest_hash is not None and is_sha256_digest(manifest_hash)
    policy_ok = policy_name in ALLOWED_POLICY_NAMES
    is_reproducible = False if entry is None else entry.is_reproducible
    is_usable = False if entry is None else entry.is_usable
    catalog_errors = 0 if entry is None else entry.error_count
    usable = (
        research_mode
        and entry is not None
        and is_reproducible
        and is_usable
        and artifacts_ok
        and catalog_errors == 0
        and policy_ok
        and backtest_hash_valid
        and manifest_hash_valid
        and error_count == 0
    )
    gate = BacktestUsabilityGate(
        usable_result=usable,
        research_mode=research_mode,
        is_reproducible=is_reproducible,
        is_usable=is_usable,
        artifacts_ok=artifacts_ok,
        policy_ok=policy_ok,
        backtest_hash_valid=backtest_hash_valid,
        manifest_hash_valid=manifest_hash_valid,
        replay_registered=replay_registered,
        error_count=error_count,
        warning_count=warning_count,
    )
    artifacts = () if integrity is None else integrity.artifacts
    return BacktestUsabilityReport(
        backtest_id=backtest_id,
        usable_result=usable,
        gate=gate,
        replay_id=None if entry is None else entry.replay_id,
        stream_hash=None if entry is None else entry.stream_hash,
        backtest_hash=backtest_hash,
        manifest_hash=manifest_hash,
        policy_name=policy_name,
        error_count=error_count,
        warning_count=warning_count,
        info_count=info_count,
        issues=ranked,
        artifacts=artifacts,
        run_root=None if run_root is None else str(run_root),
    )


def usability_report_json(report: BacktestUsabilityReport) -> str:
    return json.dumps(report.as_mapping(), indent=2, sort_keys=True, ensure_ascii=True)


def _catalog_issues(entry: BacktestRunCatalogEntry) -> list[BacktestUsabilityIssue]:
    issues: list[BacktestUsabilityIssue] = []
    if not is_sha256_digest(entry.backtest_hash):
        issues.append(
            _issue(
                BacktestUsabilitySeverity.ERROR,
                BacktestUsabilityCode.INVALID_HASH,
                "backtest_hash must be sha256:<64 hex>",
                actual=entry.backtest_hash,
            )
        )
    if not is_sha256_digest(entry.manifest_hash):
        issues.append(
            _issue(
                BacktestUsabilitySeverity.ERROR,
                BacktestUsabilityCode.INVALID_HASH,
                "manifest_hash must be sha256:<64 hex>",
                actual=entry.manifest_hash,
            )
        )
    if entry.policy_name not in ALLOWED_POLICY_NAMES:
        issues.append(
            _issue(
                BacktestUsabilitySeverity.ERROR,
                BacktestUsabilityCode.UNSUPPORTED_POLICY,
                "policy_name must be a registered research policy",
                expected=NOOP_POLICY_NAME,
                actual=entry.policy_name,
            )
        )
    if entry.error_count > 0:
        issues.append(
            _issue(
                BacktestUsabilitySeverity.ERROR,
                BacktestUsabilityCode.ERRORS_PRESENT,
                "backtest summary reports errors",
                actual=str(entry.error_count),
            )
        )
    if not entry.is_reproducible:
        issues.append(
            _issue(
                BacktestUsabilitySeverity.ERROR,
                BacktestUsabilityCode.NOT_REPRODUCIBLE,
                "catalog row is not marked reproducible",
            )
        )
    if not entry.is_usable:
        issues.append(
            _issue(
                BacktestUsabilitySeverity.ERROR,
                BacktestUsabilityCode.NOT_USABLE,
                "catalog row is not marked usable",
            )
        )
    return issues


def _integrity_issues(
    items: Sequence[BacktestArtifactVerificationIssue],
) -> list[BacktestUsabilityIssue]:
    issues: list[BacktestUsabilityIssue] = []
    for item in items:
        issues.append(
            BacktestUsabilityIssue(
                severity=item.severity,
                code=_map_integrity_code(item.code),
                message=item.message,
                path=item.path,
                expected=item.expected,
                actual=item.actual,
            )
        )
    return issues


def _map_integrity_code(code: str) -> str:
    if code in _ARTIFACT_MISSING_CODES:
        return BacktestUsabilityCode.ARTIFACT_MISSING.value
    if code in _HASH_MISMATCH_CODES:
        return BacktestUsabilityCode.ARTIFACT_HASH_MISMATCH.value
    if code == BacktestIntegrityCode.UNSUPPORTED_POLICY.value:
        return BacktestUsabilityCode.UNSUPPORTED_POLICY.value
    if code == BacktestIntegrityCode.INVALID_HASH.value:
        return BacktestUsabilityCode.INVALID_HASH.value
    if code == BacktestIntegrityCode.CATALOG_ENTRY_MISSING.value:
        return BacktestUsabilityCode.CATALOG_ENTRY_MISSING.value
    if code == BacktestIntegrityCode.SECRET_LIKE_VALUE.value:
        return BacktestUsabilityCode.NOT_REPRODUCIBLE.value
    return code


def _issue(
    severity: BacktestUsabilitySeverity,
    code: BacktestUsabilityCode,
    message: str,
    *,
    path: str | None = None,
    expected: str | None = None,
    actual: str | None = None,
) -> BacktestUsabilityIssue:
    return BacktestUsabilityIssue(
        severity=severity.value,
        code=code.value,
        message=message,
        path=path,
        expected=expected,
        actual=actual,
    )


def _rank(issues: list[BacktestUsabilityIssue]) -> tuple[BacktestUsabilityIssue, ...]:
    return tuple(
        sorted(
            issues,
            key=lambda item: (
                SEVERITY_RANK.get(item.severity, 9),
                item.code,
                item.message,
            ),
        )
    )
