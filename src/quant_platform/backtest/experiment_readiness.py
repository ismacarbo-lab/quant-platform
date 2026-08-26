"""Usability gate for dry-run backtest experiments. Not a strategy check."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy.orm import Session

from quant_platform.backtest.experiment_catalog import get_backtest_experiment_by_id
from quant_platform.backtest.experiment_integrity import (
    ExperimentArtifactVerificationReport,
    ExperimentIntegrityCode,
    resolve_experiment_directory,
    verify_backtest_experiment_artifacts,
)
from quant_platform.backtest.experiment_readiness_types import (
    BacktestExperimentMemberUsability,
    BacktestExperimentUsabilityGate,
    BacktestExperimentUsabilityIssue,
    BacktestExperimentUsabilityReport,
    ExperimentUsabilityCode,
    ExperimentUsabilitySeverity,
)
from quant_platform.backtest.experiment_types import (
    BacktestExperimentCatalogEntry,
    BacktestExperimentMember,
    member_relative_path,
)
from quant_platform.backtest.experiments import members_from_experiment_summary
from quant_platform.backtest.integrity_types import (
    SEVERITY_RANK,
    BacktestArtifactVerificationIssue,
)
from quant_platform.backtest.readiness import (
    BacktestUsabilityCode,
    BacktestUsabilityReport,
    evaluate_backtest_result_usability,
)
from quant_platform.core.config import get_settings
from quant_platform.research.snapshots import is_sha256_digest
from quant_platform.simulation.constructs import detect_trading_constructs
from quant_platform.simulation.readiness_types import TradingConstructFinding

_ARTIFACT_MISSING_CODES = frozenset(
    {
        ExperimentIntegrityCode.MISSING_DIR.value,
        ExperimentIntegrityCode.MISSING_MANIFEST.value,
        ExperimentIntegrityCode.MISSING_SUMMARY.value,
        ExperimentIntegrityCode.MISSING_ARTIFACT.value,
        ExperimentIntegrityCode.EMPTY_ARTIFACT_PATH.value,
        ExperimentIntegrityCode.ABSOLUTE_PATH.value,
        ExperimentIntegrityCode.PATH_ESCAPE.value,
    }
)
_HASH_CODES = frozenset(
    {
        ExperimentIntegrityCode.EXPERIMENT_HASH_MISMATCH.value,
        ExperimentIntegrityCode.MANIFEST_HASH_MISMATCH.value,
        ExperimentIntegrityCode.INVALID_HASH.value,
    }
)


def evaluate_backtest_experiment_usability(
    session: Session,
    experiment_id: str,
    base_dir: Path | str,
    *,
    research_mode: bool | None = None,
) -> BacktestExperimentUsabilityReport:
    """Decide whether a registered experiment is usable research evidence.

    Does not imply a profitable strategy. Does not create orders or PnL.
    """
    mode = get_settings().is_research_mode if research_mode is None else research_mode
    cleaned = experiment_id.strip()
    entry = get_backtest_experiment_by_id(session, cleaned) if cleaned else None
    root = resolve_experiment_directory(base_dir, cleaned) if cleaned else None
    integrity = None
    if root is not None:
        integrity = verify_backtest_experiment_artifacts(
            root, expected_experiment_id=cleaned or None
        )
    members: tuple[BacktestExperimentMember, ...] = ()
    if entry is not None:
        members = members_from_experiment_summary(entry.summary)
    member_reports: list[
        tuple[BacktestExperimentMember, BacktestUsabilityReport | None]
    ] = []
    for index, member in enumerate(members, start=1):
        relative = member.relative_path or member_relative_path(index)
        member_dir = None if root is None else root / relative
        report = None
        if member_dir is not None and member_dir.is_dir() and member.backtest_id:
            report = evaluate_backtest_result_usability(
                session,
                member.backtest_id,
                member_dir,
                research_mode=mode,
            )
        member_reports.append((member, report))
    findings = detect_trading_constructs()
    return build_backtest_experiment_usability_report(
        experiment_id=cleaned or experiment_id,
        entry=entry,
        integrity=integrity,
        member_reports=member_reports,
        research_mode=mode,
        experiment_root=root,
        construct_findings=findings,
    )


def build_backtest_experiment_usability_report(
    *,
    experiment_id: str,
    entry: BacktestExperimentCatalogEntry | None,
    integrity: ExperimentArtifactVerificationReport | None,
    member_reports: Sequence[
        tuple[BacktestExperimentMember, BacktestUsabilityReport | None]
    ],
    research_mode: bool = True,
    experiment_root: Path | str | None = None,
    construct_findings: Sequence[TradingConstructFinding] = (),
) -> BacktestExperimentUsabilityReport:
    """Pure usability evaluation. Used by tests without PostgreSQL."""
    issues: list[BacktestExperimentUsabilityIssue] = []
    if not research_mode:
        issues.append(
            _issue(
                ExperimentUsabilitySeverity.ERROR,
                ExperimentUsabilityCode.APP_MODE_NOT_RESEARCH,
                "APP_MODE must be research",
            )
        )
    if entry is None:
        issues.append(
            _issue(
                ExperimentUsabilitySeverity.ERROR,
                ExperimentUsabilityCode.EXPERIMENT_MISSING,
                "experiment_id is not registered",
            )
        )
    else:
        issues.extend(_catalog_issues(entry))

    artifacts_ok = False
    if integrity is None:
        issues.append(
            _issue(
                ExperimentUsabilitySeverity.ERROR,
                ExperimentUsabilityCode.EXPERIMENT_ARTIFACT_MISSING,
                "experiment directory could not be resolved under base_dir",
                path=None if experiment_root is None else str(experiment_root),
            )
        )
    else:
        artifacts_ok = integrity.ok
        issues.extend(_integrity_issues(integrity.issues))

    member_rows: list[BacktestExperimentMemberUsability] = []
    policy_output_ok = True
    members_ok = True
    for member, report in member_reports:
        row, member_issues, member_ok, output_ok = _member_view(member, report)
        member_rows.append(row)
        issues.extend(member_issues)
        members_ok = members_ok and member_ok
        policy_output_ok = policy_output_ok and output_ok

    if not member_reports:
        issues.append(
            _issue(
                ExperimentUsabilitySeverity.ERROR,
                ExperimentUsabilityCode.NO_USABLE_MEMBERS,
                "experiment has no members",
            )
        )
        members_ok = False
    elif not any(item.usable_result for item in member_rows):
        issues.append(
            _issue(
                ExperimentUsabilitySeverity.ERROR,
                ExperimentUsabilityCode.NO_USABLE_MEMBERS,
                "experiment has no usable members",
            )
        )
        members_ok = False

    if entry is not None and entry.member_count != len(member_reports):
        issues.append(
            _issue(
                ExperimentUsabilitySeverity.ERROR,
                ExperimentUsabilityCode.INCONSISTENT_MEMBER_COUNT,
                "catalog member_count does not match declared members",
                expected=str(entry.member_count),
                actual=str(len(member_reports)),
            )
        )
        members_ok = False

    expected_policy = None if entry is None else entry.policy_name
    for member, _report in member_reports:
        if expected_policy is not None and member.policy_name != expected_policy:
            issues.append(
                _issue(
                    ExperimentUsabilitySeverity.ERROR,
                    ExperimentUsabilityCode.INCONSISTENT_POLICY_NAME,
                    "member policy_name does not match the experiment",
                    expected=expected_policy,
                    actual=member.policy_name,
                    path=member.relative_path or member.backtest_id,
                )
            )

    constructs_ok = True
    for finding in construct_findings:
        constructs_ok = False
        issues.append(
            _issue(
                ExperimentUsabilitySeverity.ERROR,
                ExperimentUsabilityCode.CONSTRUCT_DETECTED,
                finding.message,
                actual=finding.name,
            )
        )

    ranked = _rank(issues)
    error_count = sum(
        1 for item in ranked if item.severity == ExperimentUsabilitySeverity.ERROR
    )
    warning_count = sum(
        1 for item in ranked if item.severity == ExperimentUsabilitySeverity.WARNING
    )
    info_count = sum(
        1 for item in ranked if item.severity == ExperimentUsabilitySeverity.INFO
    )
    experiment_hash = None if entry is None else entry.experiment_hash
    manifest_hash = None if entry is None else entry.manifest_hash
    experiment_hash_valid = experiment_hash is not None and is_sha256_digest(
        experiment_hash
    )
    manifest_hash_valid = manifest_hash is not None and is_sha256_digest(manifest_hash)
    integrity_hash_ok = True
    if integrity is not None:
        if (
            integrity.experiment_hash is not None
            and integrity.recomputed_experiment_hash is not None
            and integrity.experiment_hash != integrity.recomputed_experiment_hash
        ):
            experiment_hash_valid = False
            integrity_hash_ok = False
        if (
            integrity.manifest_hash is not None
            and integrity.recomputed_manifest_hash is not None
            and integrity.manifest_hash != integrity.recomputed_manifest_hash
        ):
            manifest_hash_valid = False
            integrity_hash_ok = False
    catalog_ok = entry is not None
    usable_count = sum(1 for item in member_rows if item.usable_result)
    experiment_usable = (
        research_mode
        and catalog_ok
        and artifacts_ok
        and experiment_hash_valid
        and manifest_hash_valid
        and integrity_hash_ok
        and members_ok
        and policy_output_ok
        and constructs_ok
        and len(member_rows) > 0
        and usable_count == len(member_rows)
        and error_count == 0
    )
    gate = BacktestExperimentUsabilityGate(
        experiment_usable=experiment_usable,
        research_mode=research_mode,
        catalog_ok=catalog_ok,
        artifacts_ok=artifacts_ok,
        experiment_hash_valid=experiment_hash_valid,
        manifest_hash_valid=manifest_hash_valid,
        members_ok=members_ok,
        policy_output_ok=policy_output_ok,
        constructs_ok=constructs_ok,
        error_count=error_count,
        warning_count=warning_count,
    )
    member_count = len(member_rows)
    if member_count == 0 and entry is not None:
        member_count = entry.member_count
    return BacktestExperimentUsabilityReport(
        experiment_id=experiment_id,
        experiment_usable=experiment_usable,
        gate=gate,
        experiment_name=None if entry is None else entry.experiment_name,
        policy_name=None if entry is None else entry.policy_name,
        experiment_hash=experiment_hash,
        manifest_hash=manifest_hash,
        member_count=member_count,
        usable_count=usable_count,
        error_count=error_count,
        warning_count=warning_count,
        info_count=info_count,
        issues=ranked,
        members=tuple(member_rows),
        experiment_root=None if experiment_root is None else str(experiment_root),
    )


def experiment_usability_report_json(
    report: BacktestExperimentUsabilityReport,
) -> str:
    return json.dumps(report.as_mapping(), indent=2, sort_keys=True, ensure_ascii=True)


def _catalog_issues(
    entry: BacktestExperimentCatalogEntry,
) -> list[BacktestExperimentUsabilityIssue]:
    issues: list[BacktestExperimentUsabilityIssue] = []
    if not is_sha256_digest(entry.experiment_hash):
        issues.append(
            _issue(
                ExperimentUsabilitySeverity.ERROR,
                ExperimentUsabilityCode.INVALID_HASH,
                "experiment_hash must be sha256:<64 hex>",
                actual=entry.experiment_hash,
            )
        )
    if not is_sha256_digest(entry.manifest_hash):
        issues.append(
            _issue(
                ExperimentUsabilitySeverity.ERROR,
                ExperimentUsabilityCode.INVALID_HASH,
                "manifest_hash must be sha256:<64 hex>",
                actual=entry.manifest_hash,
            )
        )
    if entry.member_count <= 0:
        issues.append(
            _issue(
                ExperimentUsabilitySeverity.ERROR,
                ExperimentUsabilityCode.NO_USABLE_MEMBERS,
                "catalog member_count must be > 0",
                actual=str(entry.member_count),
            )
        )
    return issues


def _member_view(
    member: BacktestExperimentMember,
    report: BacktestUsabilityReport | None,
) -> tuple[
    BacktestExperimentMemberUsability,
    list[BacktestExperimentUsabilityIssue],
    bool,
    bool,
]:
    issues: list[BacktestExperimentUsabilityIssue] = []
    path = member.relative_path or member.backtest_id
    if report is None:
        issues.append(
            _issue(
                ExperimentUsabilitySeverity.ERROR,
                ExperimentUsabilityCode.MEMBER_BACKTEST_MISSING,
                "member backtest is missing from disk or catalog",
                path=path,
                actual=member.backtest_id,
            )
        )
        row = BacktestExperimentMemberUsability(
            replay_id=member.replay_id,
            backtest_id=member.backtest_id,
            relative_path=member.relative_path,
            policy_name=member.policy_name,
            usable_result=False,
            warning_count=member.warning_count,
            error_count=member.error_count,
            policy_output_ok=False,
            artifacts_ok=False,
        )
        return row, issues, False, False
    usable = report.usable_result
    artifacts_ok = report.gate.artifacts_ok
    output_ok = report.gate.policy_output_ok
    if not usable:
        issues.append(
            _issue(
                ExperimentUsabilitySeverity.ERROR,
                ExperimentUsabilityCode.MEMBER_NOT_USABLE,
                "member backtest is not usable research evidence",
                path=path,
                actual=member.backtest_id,
            )
        )
    if not artifacts_ok:
        issues.append(
            _issue(
                ExperimentUsabilitySeverity.ERROR,
                ExperimentUsabilityCode.MEMBER_ARTIFACT_INVALID,
                "member backtest artifacts failed verification",
                path=path,
                actual=member.backtest_id,
            )
        )
    if not output_ok:
        code = ExperimentUsabilityCode.POLICY_OUTPUT_INVALID
        for item in report.issues:
            if item.code in {
                BacktestUsabilityCode.POLICY_OUTPUT_INVALID.value,
                ExperimentUsabilityCode.FORBIDDEN_OPERATIONAL_LANGUAGE.value,
            }:
                if "investment-decision" in item.message or item.code.endswith(
                    "forbidden_operational_language"
                ):
                    code = ExperimentUsabilityCode.FORBIDDEN_OPERATIONAL_LANGUAGE
                break
        issues.append(
            _issue(
                ExperimentUsabilitySeverity.ERROR,
                code,
                "member policy output is not valid research evidence",
                path=path,
                actual=member.backtest_id,
            )
        )
    row = BacktestExperimentMemberUsability(
        replay_id=member.replay_id,
        backtest_id=member.backtest_id,
        relative_path=member.relative_path,
        policy_name=report.policy_name or member.policy_name,
        usable_result=usable,
        warning_count=report.warning_count,
        error_count=report.error_count,
        policy_output_ok=output_ok,
        artifacts_ok=artifacts_ok,
    )
    return row, issues, usable and artifacts_ok and output_ok, output_ok


def _integrity_issues(
    items: Sequence[BacktestArtifactVerificationIssue],
) -> list[BacktestExperimentUsabilityIssue]:
    issues: list[BacktestExperimentUsabilityIssue] = []
    for item in items:
        issues.append(
            BacktestExperimentUsabilityIssue(
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
        return ExperimentUsabilityCode.EXPERIMENT_ARTIFACT_MISSING.value
    if code in _HASH_CODES:
        return ExperimentUsabilityCode.EXPERIMENT_HASH_MISMATCH.value
    if code == ExperimentIntegrityCode.MEMBER_BACKTEST_ID_MISMATCH.value:
        return ExperimentUsabilityCode.MEMBER_BACKTEST_MISSING.value
    if code == ExperimentIntegrityCode.FORBIDDEN_OPERATIONAL_LANGUAGE.value:
        return ExperimentUsabilityCode.FORBIDDEN_OPERATIONAL_LANGUAGE.value
    if code == ExperimentIntegrityCode.COUNT_MISMATCH.value:
        return ExperimentUsabilityCode.INCONSISTENT_MEMBER_COUNT.value
    return code


def _issue(
    severity: ExperimentUsabilitySeverity,
    code: ExperimentUsabilityCode,
    message: str,
    *,
    path: str | None = None,
    expected: str | None = None,
    actual: str | None = None,
) -> BacktestExperimentUsabilityIssue:
    return BacktestExperimentUsabilityIssue(
        severity=severity.value,
        code=code.value,
        message=message,
        path=path,
        expected=expected,
        actual=actual,
    )


def _rank(
    issues: list[BacktestExperimentUsabilityIssue],
) -> tuple[BacktestExperimentUsabilityIssue, ...]:
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
