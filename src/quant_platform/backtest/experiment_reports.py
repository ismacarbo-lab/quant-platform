"""Aggregated experiment research reports. Counts and hashes only; no PnL."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path

from quant_platform.backtest.errors import BacktestError, BacktestErrorCode
from quant_platform.backtest.experiment_readiness_types import (
    EXPERIMENT_REPORT_HASH_FORMAT_VERSION,
    EXPERIMENT_REPORT_HASH_KIND,
    BacktestExperimentMemberComparisonSummary,
    BacktestExperimentObservationAggregate,
    BacktestExperimentResearchMember,
    BacktestExperimentResearchReport,
)
from quant_platform.backtest.experiment_types import (
    BacktestExperimentCatalogEntry,
    BacktestExperimentMember,
    member_relative_path,
)
from quant_platform.backtest.experiments import members_from_experiment_summary
from quant_platform.backtest.observation_reports import (
    ObservationKindSummary,
    ObservationReport,
    ObservationSeveritySummary,
    build_observation_report,
)
from quant_platform.backtest.observations import contains_operative_language
from quant_platform.research.snapshots import (
    canonical_json,
    is_sha256_digest,
    manifest_contains_secrets,
    sha256_canonical,
)


def hash_backtest_experiment_report(
    report: BacktestExperimentResearchReport | Mapping[str, object],
) -> str:
    """SHA-256 of the research report definition. No wall-clock or paths."""
    if isinstance(report, BacktestExperimentResearchReport):
        payload = report.as_mapping(include_report_hash=False)
    else:
        payload = dict(report)
        payload.pop("report_hash", None)
    payload.pop("experiment_root", None)
    members = payload.get("members")
    if isinstance(members, list):
        payload["members"] = sorted(members, key=canonical_json)
    replay_ids = payload.get("replay_ids")
    if isinstance(replay_ids, list):
        payload["replay_ids"] = sorted(str(item) for item in replay_ids)
    stream_hashes = payload.get("stream_hashes")
    if isinstance(stream_hashes, list):
        payload["stream_hashes"] = sorted(str(item) for item in stream_hashes)
    backtest_hashes = payload.get("backtest_hashes")
    if isinstance(backtest_hashes, list):
        payload["backtest_hashes"] = sorted(str(item) for item in backtest_hashes)
    configs = payload.get("policy_configs")
    if isinstance(configs, list):
        payload["policy_configs"] = sorted(
            [dict(item) for item in configs if isinstance(item, dict)],
            key=canonical_json,
        )
    digest_payload = {
        "kind": EXPERIMENT_REPORT_HASH_KIND,
        "version": EXPERIMENT_REPORT_HASH_FORMAT_VERSION,
        "experiment_id": payload.get("experiment_id"),
        "experiment_name": payload.get("experiment_name"),
        "policy_name": payload.get("policy_name"),
        "experiment_hash": payload.get("experiment_hash"),
        "member_count": payload.get("member_count"),
        "usable_count": payload.get("usable_count"),
        "warning_count": payload.get("warning_count"),
        "error_count": payload.get("error_count"),
        "policy_configs": payload.get("policy_configs"),
        "replay_ids": payload.get("replay_ids"),
        "stream_hashes": payload.get("stream_hashes"),
        "backtest_hashes": payload.get("backtest_hashes"),
        "observations": payload.get("observations"),
        "comparison": payload.get("comparison"),
        "members": payload.get("members"),
    }
    blob = canonical_json(digest_payload)
    if manifest_contains_secrets(blob):
        raise BacktestError(
            "experiment research report must not contain secrets",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    if contains_operative_language(blob):
        raise BacktestError(
            "experiment research report must not contain investment-decision wording",
            code=BacktestErrorCode.INVALID_POLICY,
        )
    return sha256_canonical(digest_payload)


def build_backtest_experiment_research_report(
    *,
    experiment_id: str,
    experiment_name: str,
    policy_name: str,
    experiment_hash: str,
    members: Sequence[BacktestExperimentMember | BacktestExperimentResearchMember],
    observation_reports: Sequence[ObservationReport] = (),
    policy_configs: Sequence[Mapping[str, object]] | None = None,
    replay_ids: Sequence[str] | None = None,
) -> BacktestExperimentResearchReport:
    """Aggregate member hashes and observations. Does not compute PnL."""
    ranked = _rank_members(members)
    if not ranked:
        raise BacktestError(
            "experiment research report requires at least one member",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    if not is_sha256_digest(experiment_hash):
        raise BacktestError(
            "experiment_hash must be sha256:<64 hex>",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    configs = _configs(policy_configs, ranked)
    ids = _replay_ids(replay_ids, ranked)
    stream_hashes = tuple(sorted({item.stream_hash for item in ranked}))
    backtest_hashes = tuple(sorted({item.backtest_hash for item in ranked}))
    observations = aggregate_experiment_observations(observation_reports)
    comparison = _comparison(ranked)
    draft = BacktestExperimentResearchReport(
        experiment_id=experiment_id,
        experiment_name=experiment_name,
        policy_name=policy_name,
        member_count=len(ranked),
        usable_count=sum(1 for item in ranked if item.usable_result),
        warning_count=sum(item.warning_count for item in ranked),
        error_count=sum(item.error_count for item in ranked),
        policy_configs=configs,
        replay_ids=ids,
        stream_hashes=stream_hashes,
        backtest_hashes=backtest_hashes,
        observations=observations,
        comparison=comparison,
        members=ranked,
        experiment_hash=experiment_hash,
        report_hash="",
    )
    return replace(draft, report_hash=hash_backtest_experiment_report(draft))


def build_research_report_from_catalog(
    entry: BacktestExperimentCatalogEntry,
    *,
    observation_reports: Sequence[ObservationReport] = (),
    members: Sequence[BacktestExperimentMember] | None = None,
) -> BacktestExperimentResearchReport:
    resolved = (
        tuple(members)
        if members is not None
        else members_from_experiment_summary(entry.summary)
    )
    raw_configs = entry.summary.get("policy_configs")
    configs = (
        [dict(item) for item in raw_configs if isinstance(item, dict)]
        if isinstance(raw_configs, list)
        else None
    )
    raw_ids = entry.summary.get("replay_ids")
    replay_ids = [str(item) for item in raw_ids] if isinstance(raw_ids, list) else None
    return build_backtest_experiment_research_report(
        experiment_id=entry.experiment_id,
        experiment_name=entry.experiment_name,
        policy_name=entry.policy_name,
        experiment_hash=entry.experiment_hash,
        members=resolved,
        observation_reports=observation_reports,
        policy_configs=configs,
        replay_ids=replay_ids,
    )


def load_member_observation_reports(
    experiment_root: Path | str,
    members: Sequence[BacktestExperimentMember],
) -> tuple[ObservationReport, ...]:
    reports: list[ObservationReport] = []
    root = Path(experiment_root)
    for index, member in enumerate(members, start=1):
        relative = member.relative_path or member_relative_path(index)
        folder = root / relative
        try:
            reports.append(build_observation_report(folder))
        except BacktestError:
            continue
    return tuple(reports)


def aggregate_experiment_observations(
    reports: Sequence[ObservationReport],
) -> BacktestExperimentObservationAggregate:
    kind_counts: Counter[str] = Counter()
    severity_counts: Counter[str] = Counter()
    unknown = 0
    corrections = 0
    corporate_actions = 0
    sessions = 0
    warnings = 0
    errors = 0
    observations = 0
    for report in reports:
        observations += report.observation_count
        warnings += report.warning_count
        errors += report.error_count
        unknown += report.unknown_event_count
        corrections += report.correction_count
        corporate_actions += report.corporate_action_count
        sessions += report.session_count
        for kind_row in report.kinds:
            kind_counts[kind_row.kind] += kind_row.count
        for severity_row in report.severities:
            severity_counts[severity_row.severity] += severity_row.count
    kinds = tuple(
        ObservationKindSummary(kind=kind, count=count)
        for kind, count in sorted(kind_counts.items())
    )
    severities = tuple(
        ObservationSeveritySummary(severity=name, count=severity_counts[name])
        for name in ("error", "warning", "info")
        if severity_counts.get(name, 0) > 0
    )
    return BacktestExperimentObservationAggregate(
        observation_count=observations,
        warning_count=warnings,
        error_count=errors,
        unknown_event_count=unknown,
        correction_count=corrections,
        corporate_action_count=corporate_actions,
        session_count=sessions,
        kinds=kinds,
        severities=severities,
    )


def _rank_members(
    members: Sequence[BacktestExperimentMember | BacktestExperimentResearchMember],
) -> tuple[BacktestExperimentResearchMember, ...]:
    rows: list[BacktestExperimentResearchMember] = []
    for item in members:
        if isinstance(item, BacktestExperimentResearchMember):
            rows.append(item)
            continue
        rows.append(
            BacktestExperimentResearchMember(
                replay_id=item.replay_id,
                backtest_id=item.backtest_id,
                stream_hash=item.stream_hash,
                backtest_hash=item.backtest_hash,
                policy_name=item.policy_name,
                policy_config=dict(item.policy_config),
                usable_result=item.usable_result,
                warning_count=item.warning_count,
                error_count=item.error_count,
            )
        )
    return tuple(
        sorted(
            rows,
            key=lambda item: (
                item.replay_id,
                item.backtest_hash,
                item.backtest_id,
            ),
        )
    )


def _configs(
    values: Sequence[Mapping[str, object]] | None,
    members: Sequence[BacktestExperimentResearchMember],
) -> tuple[dict[str, object], ...]:
    if values is None:
        unique = []
        seen: set[str] = set()
        for item in members:
            blob = canonical_json(item.policy_config)
            if blob in seen:
                continue
            seen.add(blob)
            unique.append(dict(item.policy_config))
        return tuple(sorted(unique, key=canonical_json))
    return tuple(sorted((dict(item) for item in values), key=canonical_json))


def _replay_ids(
    values: Sequence[str] | None,
    members: Sequence[BacktestExperimentResearchMember],
) -> tuple[str, ...]:
    if values is None:
        return tuple(sorted({item.replay_id for item in members}))
    return tuple(sorted({item.strip() for item in values if item.strip()}))


def _comparison(
    members: Sequence[BacktestExperimentResearchMember],
) -> BacktestExperimentMemberComparisonSummary:
    policies = {item.policy_name for item in members}
    streams = {item.stream_hash for item in members}
    hashes = {item.backtest_hash for item in members}
    configs = {canonical_json(item.policy_config) for item in members}
    replays = {item.replay_id for item in members}
    return BacktestExperimentMemberComparisonSummary(
        distinct_replay_id_count=len(replays),
        distinct_stream_hash_count=len(streams),
        distinct_backtest_hash_count=len(hashes),
        distinct_policy_config_count=len(configs),
        same_policy_name=len(policies) == 1,
        same_stream_hash=len(streams) == 1,
        same_backtest_hash=len(hashes) == 1,
    )
