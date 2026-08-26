"""Backtest readiness gate for registered replay runs. Not a backtester."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy.orm import Session

from quant_platform.core.config import get_settings
from quant_platform.research.snapshots import canonical_json, is_sha256_digest
from quant_platform.simulation.constructs import (
    detect_trading_constructs,
    event_kinds_from_counts,
)
from quant_platform.simulation.readiness_types import (
    SEVERITY_RANK,
    BacktestReadinessGate,
    ReplayRunReadinessCode,
    ReplayRunReadinessIssue,
    ReplayRunReadinessReport,
    ReplayRunReadinessSeverity,
    TradingConstructFinding,
)
from quant_platform.simulation.run_catalog import get_replay_run_by_id
from quant_platform.simulation.run_integrity import (
    ReplayRunIntegrityCode,
    ReplayRunIntegrityReport,
    verify_registered_replay_run,
)
from quant_platform.simulation.run_types import (
    MANIFEST_ARTIFACT_NAME,
    ReplayRunCatalogEntry,
)
from quant_platform.simulation.summary import SOURCE_SNAPSHOT

_ARTIFACT_MISSING_CODES = frozenset(
    {
        ReplayRunIntegrityCode.MISSING_ARTIFACT.value,
        ReplayRunIntegrityCode.MISSING_MANIFEST.value,
        ReplayRunIntegrityCode.MISSING_RUN_DIR.value,
        ReplayRunIntegrityCode.EMPTY_ARTIFACT_PATH.value,
    }
)
_HASH_MISMATCH_CODES = frozenset(
    {
        ReplayRunIntegrityCode.STREAM_HASH_MISMATCH.value,
        ReplayRunIntegrityCode.MANIFEST_HASH_MISMATCH.value,
        ReplayRunIntegrityCode.CATALOG_MANIFEST_MISMATCH.value,
        ReplayRunIntegrityCode.EVENT_COUNT_MISMATCH.value,
        ReplayRunIntegrityCode.COUNT_MISMATCH.value,
    }
)
_NOT_REPRODUCIBLE_CODES = frozenset(
    {
        ReplayRunIntegrityCode.INVALID_HASH.value,
        ReplayRunIntegrityCode.INVALID_JSON.value,
        ReplayRunIntegrityCode.SECRET_LIKE_VALUE.value,
        ReplayRunIntegrityCode.ABSOLUTE_PATH.value,
        ReplayRunIntegrityCode.PATH_ESCAPE.value,
        ReplayRunIntegrityCode.CATALOG_ENTRY_MISSING.value,
    }
)


def evaluate_replay_run_readiness(
    session: Session,
    replay_id: str,
    base_dir: Path | str,
    *,
    research_mode: bool | None = None,
) -> ReplayRunReadinessReport:
    """Load a catalog row, verify local artifacts, and apply the readiness gate.

    Does not run a strategy, compute PnL, or create orders.
    """
    mode = get_settings().is_research_mode if research_mode is None else research_mode
    cleaned = replay_id.strip()
    entry = get_replay_run_by_id(session, cleaned) if cleaned else None
    run_root = resolve_replay_run_directory(base_dir, cleaned) if cleaned else None
    integrity: ReplayRunIntegrityReport | None = None
    if cleaned and run_root is not None:
        integrity = verify_registered_replay_run(session, cleaned, run_root)
    constructs = detect_trading_constructs(event_kinds=_event_kinds_for(entry))
    return build_readiness_report(
        replay_id=cleaned or replay_id,
        entry=entry,
        integrity=integrity,
        constructs=constructs,
        research_mode=mode,
        run_root=run_root,
    )


def build_readiness_report(
    *,
    replay_id: str,
    entry: ReplayRunCatalogEntry | None,
    integrity: ReplayRunIntegrityReport | None,
    constructs: Sequence[TradingConstructFinding] = (),
    research_mode: bool = True,
    run_root: Path | str | None = None,
) -> ReplayRunReadinessReport:
    """Pure readiness evaluation. Used by tests without PostgreSQL."""
    issues: list[ReplayRunReadinessIssue] = []
    if not research_mode:
        issues.append(
            _issue(
                ReplayRunReadinessSeverity.ERROR,
                ReplayRunReadinessCode.APP_MODE_NOT_RESEARCH,
                "APP_MODE must be research",
            )
        )
    if entry is None:
        issues.append(
            _issue(
                ReplayRunReadinessSeverity.ERROR,
                ReplayRunReadinessCode.CATALOG_ENTRY_MISSING,
                "replay_id is not registered",
            )
        )
    else:
        issues.extend(_catalog_issues(entry))
    if integrity is None:
        issues.append(
            _issue(
                ReplayRunReadinessSeverity.ERROR,
                ReplayRunReadinessCode.ARTIFACT_MISSING,
                "replay run directory could not be resolved under base_dir",
                path=None if run_root is None else str(run_root),
            )
        )
    else:
        issues.extend(_integrity_issues(integrity))
    for finding in constructs:
        issues.append(
            _issue(
                ReplayRunReadinessSeverity.ERROR,
                ReplayRunReadinessCode.TRADING_CONSTRUCT_DETECTED,
                finding.message,
                actual=finding.name,
            )
        )

    ranked = _rank_issues(issues)
    error_count = sum(
        1 for item in ranked if item.severity == ReplayRunReadinessSeverity.ERROR
    )
    warning_count = sum(
        1 for item in ranked if item.severity == ReplayRunReadinessSeverity.WARNING
    )
    info_count = sum(
        1 for item in ranked if item.severity == ReplayRunReadinessSeverity.INFO
    )
    artifacts_ok = integrity is not None and integrity.ok
    stream_hash = None if entry is None else entry.stream_hash
    manifest_hash = None if entry is None else entry.manifest_hash
    stream_hash_valid = stream_hash is not None and is_sha256_digest(stream_hash)
    manifest_hash_valid = manifest_hash is not None and is_sha256_digest(manifest_hash)
    boundary_ok = False if entry is None else entry.boundary_ok
    is_reproducible = False if entry is None else entry.is_reproducible
    is_usable = False if entry is None else entry.is_usable
    catalog_errors = 0 if entry is None else entry.error_count
    trading_ok = len(constructs) == 0
    ready = (
        research_mode
        and entry is not None
        and catalog_errors == 0
        and boundary_ok
        and is_reproducible
        and is_usable
        and artifacts_ok
        and stream_hash_valid
        and manifest_hash_valid
        and trading_ok
        and error_count == 0
    )
    gate = BacktestReadinessGate(
        ready_for_backtest=ready,
        research_mode=research_mode,
        error_count=error_count,
        warning_count=warning_count,
        boundary_ok=boundary_ok,
        is_reproducible=is_reproducible,
        is_usable=is_usable,
        artifacts_ok=artifacts_ok,
        stream_hash_valid=stream_hash_valid,
        trading_constructs_ok=trading_ok,
    )
    artifacts = () if integrity is None else integrity.artifacts
    return ReplayRunReadinessReport(
        replay_id=replay_id,
        ready_for_backtest=ready,
        gate=gate,
        stream_hash=stream_hash,
        manifest_hash=manifest_hash,
        boundary_ok=None if entry is None else entry.boundary_ok,
        error_count=error_count,
        warning_count=warning_count,
        info_count=info_count,
        issues=ranked,
        artifacts=artifacts,
        run_root=None if run_root is None else str(run_root),
    )


def resolve_replay_run_directory(base_dir: Path | str, replay_id: str) -> Path | None:
    """Find a replay-run folder for ``replay_id`` under ``base_dir``."""
    cleaned = replay_id.strip()
    if not cleaned:
        return None
    base = Path(base_dir).expanduser()
    if not base.exists() or base.is_file():
        return None
    direct = base / MANIFEST_ARTIFACT_NAME
    if direct.is_file() and _manifest_file_replay_id(direct) == cleaned:
        return base
    named = base / cleaned
    named_manifest = named / MANIFEST_ARTIFACT_NAME
    if named_manifest.is_file() and _manifest_file_replay_id(named_manifest) == cleaned:
        return named
    if not base.is_dir():
        return None
    matches: list[Path] = []
    for child in sorted(base.iterdir()):
        if not child.is_dir():
            continue
        manifest = child / MANIFEST_ARTIFACT_NAME
        if manifest.is_file() and _manifest_file_replay_id(manifest) == cleaned:
            matches.append(child)
    if len(matches) == 1:
        return matches[0]
    return None


def readiness_report_json(report: ReplayRunReadinessReport) -> str:
    return json.dumps(report.as_mapping(), indent=2, sort_keys=True, ensure_ascii=True)


def readiness_canonical_json(report: ReplayRunReadinessReport) -> str:
    """Compact canonical JSON for equality tests."""
    return canonical_json(report.as_mapping())


def _catalog_issues(entry: ReplayRunCatalogEntry) -> list[ReplayRunReadinessIssue]:
    issues: list[ReplayRunReadinessIssue] = []
    if not is_sha256_digest(entry.stream_hash):
        issues.append(
            _issue(
                ReplayRunReadinessSeverity.ERROR,
                ReplayRunReadinessCode.INVALID_HASH,
                "stream_hash must be sha256:<64 hex>",
                actual=entry.stream_hash,
            )
        )
    if not is_sha256_digest(entry.manifest_hash):
        issues.append(
            _issue(
                ReplayRunReadinessSeverity.ERROR,
                ReplayRunReadinessCode.INVALID_HASH,
                "manifest_hash must be sha256:<64 hex>",
                actual=entry.manifest_hash,
            )
        )
    if not entry.boundary_ok:
        issues.append(
            _issue(
                ReplayRunReadinessSeverity.ERROR,
                ReplayRunReadinessCode.BOUNDARY_NOT_OK,
                "boundary_ok is false",
            )
        )
    if entry.error_count > 0:
        issues.append(
            _issue(
                ReplayRunReadinessSeverity.ERROR,
                ReplayRunReadinessCode.AUDIT_ERRORS_PRESENT,
                "audit summary reports errors",
                actual=str(entry.error_count),
            )
        )
    if not entry.is_reproducible:
        issues.append(
            _issue(
                ReplayRunReadinessSeverity.ERROR,
                ReplayRunReadinessCode.NOT_REPRODUCIBLE,
                "catalog row is not marked reproducible",
            )
        )
    if not entry.is_usable:
        issues.append(
            _issue(
                ReplayRunReadinessSeverity.ERROR,
                ReplayRunReadinessCode.NOT_USABLE,
                "catalog row is not marked usable",
            )
        )
    if entry.source_type == SOURCE_SNAPSHOT and not entry.dataset_snapshot_id:
        issues.append(
            _issue(
                ReplayRunReadinessSeverity.WARNING,
                ReplayRunReadinessCode.MISSING_DATASET_SNAPSHOT_LINK,
                "snapshot replay has no dataset_snapshot_id",
            )
        )
    elif entry.source_type == SOURCE_SNAPSHOT:
        issues.append(
            _issue(
                ReplayRunReadinessSeverity.INFO,
                ReplayRunReadinessCode.SNAPSHOT_NOT_VERIFIED,
                "dataset snapshot artifacts are not verified by this gate",
                actual=entry.dataset_snapshot_id,
            )
        )
    if entry.git_commit is None:
        issues.append(
            _issue(
                ReplayRunReadinessSeverity.INFO,
                ReplayRunReadinessCode.DIRTY_GIT_STATE_UNKNOWN,
                "git_commit is missing; package provenance is unknown",
            )
        )
    return issues


def _integrity_issues(
    report: ReplayRunIntegrityReport,
) -> list[ReplayRunReadinessIssue]:
    issues: list[ReplayRunReadinessIssue] = []
    for item in report.issues:
        issues.append(
            ReplayRunReadinessIssue(
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
        return ReplayRunReadinessCode.ARTIFACT_MISSING.value
    if code in _HASH_MISMATCH_CODES:
        return ReplayRunReadinessCode.ARTIFACT_HASH_MISMATCH.value
    if code in _NOT_REPRODUCIBLE_CODES:
        return ReplayRunReadinessCode.NOT_REPRODUCIBLE.value
    return code


def _event_kinds_for(entry: ReplayRunCatalogEntry | None) -> tuple[str, ...]:
    if entry is None:
        return ()
    return event_kinds_from_counts(entry.audit_summary.get("counts_by_kind"))


def _manifest_file_replay_id(path: Path) -> str | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    raw = payload.get("replay_id")
    if not isinstance(raw, str) or not raw.strip():
        return None
    return raw.strip()


def _issue(
    severity: ReplayRunReadinessSeverity,
    code: ReplayRunReadinessCode,
    message: str,
    *,
    path: str | None = None,
    expected: str | None = None,
    actual: str | None = None,
) -> ReplayRunReadinessIssue:
    return ReplayRunReadinessIssue(
        severity=severity.value,
        code=code.value,
        message=message,
        path=path,
        expected=expected,
        actual=actual,
    )


def _rank_issues(
    issues: list[ReplayRunReadinessIssue],
) -> tuple[ReplayRunReadinessIssue, ...]:
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
