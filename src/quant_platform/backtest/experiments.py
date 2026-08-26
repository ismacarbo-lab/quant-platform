"""Dry-run backtest experiments. Groups research runs; not a strategy."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from quant_platform.backtest.catalog import (
    backtest_run_is_usable,
    register_backtest_run,
)
from quant_platform.backtest.engine import run_backtest_from_replay_run
from quant_platform.backtest.errors import BacktestError, BacktestErrorCode
from quant_platform.backtest.experiment_artifacts import (
    write_backtest_experiment_artifacts,
)
from quant_platform.backtest.experiment_types import (
    EXPERIMENT_HASH_FORMAT_VERSION,
    EXPERIMENT_HASH_KIND,
    BacktestExperimentManifest,
    BacktestExperimentMember,
    BacktestExperimentRequest,
    BacktestExperimentResult,
    BacktestExperimentSummary,
    member_relative_path,
)
from quant_platform.backtest.integrity import verify_backtest_artifacts
from quant_platform.backtest.readiness import evaluate_backtest_result_usability
from quant_platform.backtest.types import BacktestManifest, BacktestRequest
from quant_platform.core.config import get_settings
from quant_platform.research.snapshots import (
    canonical_json,
    is_sha256_digest,
    sha256_canonical,
)


def derive_experiment_id(experiment_hash: str) -> UUID:
    """Stable UUID from ``experiment_hash``. Default runs still use UUID4."""
    if not is_sha256_digest(experiment_hash):
        raise BacktestError(
            "experiment_hash must be sha256:<64 hex>",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    digest = hashlib.sha256(experiment_hash.encode("utf-8")).digest()
    return UUID(bytes=digest[:16])


def hash_backtest_experiment(
    result_or_manifest: BacktestExperimentResult | BacktestExperimentManifest,
) -> str:
    """SHA-256 of experiment definition and member hashes. No wall-clock."""
    if isinstance(result_or_manifest, BacktestExperimentManifest):
        return hash_experiment_mapping(
            request=result_or_manifest.request,
            members=members_from_experiment_summary(result_or_manifest.summary),
        )
    return hash_experiment_mapping(
        request=result_or_manifest.request.as_mapping(),
        members=result_or_manifest.members,
    )


def hash_experiment_mapping(
    *,
    request: Mapping[str, object] | BacktestExperimentRequest,
    members: Sequence[BacktestExperimentMember | Mapping[str, object]],
) -> str:
    if isinstance(request, BacktestExperimentRequest):
        name = request.experiment_name
        replay_ids = list(request.replay_ids)
        policy_name = request.policy_name
        configs = [dict(item) for item in request.policy_configs]
    else:
        name = str(request.get("experiment_name") or "")
        raw_ids = request.get("replay_ids")
        replay_ids = (
            [str(item) for item in raw_ids] if isinstance(raw_ids, list) else []
        )
        policy_name = str(request.get("policy_name") or "")
        raw_configs = request.get("policy_configs")
        configs = (
            [dict(item) for item in raw_configs if isinstance(item, dict)]
            if isinstance(raw_configs, list)
            else []
        )
    member_payloads = [_member_hash_payload(item) for item in members]
    ranked_members = sorted(member_payloads, key=canonical_json)
    payload = {
        "kind": EXPERIMENT_HASH_KIND,
        "version": EXPERIMENT_HASH_FORMAT_VERSION,
        "experiment_name": name,
        "replay_ids": sorted(replay_ids),
        "policy_name": policy_name,
        "policy_configs": sorted(configs, key=canonical_json),
        "members": ranked_members,
        "usable_count": sum(1 for item in ranked_members if item.get("usable_result")),
        "warning_count": sum(
            _as_count(item.get("warning_count")) for item in ranked_members
        ),
        "error_count": sum(
            _as_count(item.get("error_count")) for item in ranked_members
        ),
    }
    return sha256_canonical(payload)


def build_experiment_result(
    request: BacktestExperimentRequest,
    members: Sequence[BacktestExperimentMember],
    *,
    experiment_id: str | None = None,
) -> BacktestExperimentResult:
    """Assemble summary and experiment_hash. Does not write files."""
    ranked = tuple(members)
    experiment_hash = hash_experiment_mapping(request=request, members=ranked)
    if experiment_id is None:
        if request.deterministic_ids:
            experiment_id = str(derive_experiment_id(experiment_hash))
        else:
            experiment_id = str(uuid4())
    usable_count = sum(1 for item in ranked if item.usable_result)
    error_count = sum(item.error_count for item in ranked)
    warning_count = sum(item.warning_count for item in ranked)
    summary = BacktestExperimentSummary(
        experiment_id=experiment_id,
        experiment_name=request.experiment_name,
        experiment_hash=experiment_hash,
        policy_name=request.policy_name,
        member_count=len(ranked),
        usable_count=usable_count,
        error_count=error_count,
        warning_count=warning_count,
        replay_ids=request.replay_ids,
        policy_configs=request.policy_configs,
        members=ranked,
    )
    return BacktestExperimentResult(
        request=request,
        summary=summary,
        members=ranked,
    )


def run_backtest_experiment(
    session: Session,
    request: BacktestExperimentRequest,
    replay_base_dir: Path | str,
    output_dir: Path | str,
    *,
    register: bool = False,
    created_at: datetime | None = None,
    git_commit: str | None = None,
    resolve_git: bool = True,
    research_mode: bool | None = None,
) -> BacktestExperimentResult:
    """Run allowed research policies over ready replay runs.

    Does not emit signals, orders, or PnL.
    """
    mode = get_settings().is_research_mode if research_mode is None else research_mode
    if not mode:
        raise BacktestError(
            "APP_MODE must be research",
            code=BacktestErrorCode.APP_MODE_NOT_RESEARCH,
        )
    members: list[BacktestExperimentMember] = []
    index = 0
    for replay_id in request.replay_ids:
        for config in request.policy_configs:
            index += 1
            relative = member_relative_path(index)
            member_dir = Path(output_dir) / relative
            backtest_request = BacktestRequest(
                replay_id=replay_id,
                deterministic_id=request.deterministic_ids,
                policy_name=request.policy_name,
                policy_config=dict(config),
                notes=request.notes,
            )
            result = run_backtest_from_replay_run(
                session,
                backtest_request,
                replay_base_dir,
                output_dir=member_dir,
                created_at=created_at,
                git_commit=git_commit,
                resolve_git=resolve_git,
                research_mode=mode,
            )
            if result.manifest is None:
                raise BacktestError(
                    "experiment members require written backtest artifacts",
                    code=BacktestErrorCode.BROKEN_RUN,
                )
            usable = _member_usable(
                session,
                result.manifest,
                member_dir,
                register=register,
                research_mode=mode,
            )
            members.append(
                BacktestExperimentMember(
                    replay_id=result.summary.replay_id,
                    backtest_id=str(result.summary.backtest_id),
                    stream_hash=result.summary.stream_hash,
                    backtest_hash=result.summary.backtest_hash,
                    policy_name=result.summary.policy_name,
                    policy_config=dict(result.summary.policy_config),
                    usable_result=usable,
                    warning_count=result.summary.warning_count,
                    error_count=result.summary.error_count,
                    relative_path=relative,
                )
            )
    assembled = build_experiment_result(request, members)
    written = write_backtest_experiment_artifacts(
        assembled,
        output_dir,
        created_at=created_at,
        git_commit=git_commit,
        resolve_git=resolve_git,
    )
    if register:
        from quant_platform.backtest.experiment_catalog import (
            register_backtest_experiment,
        )

        if written.manifest is None:
            raise BacktestError(
                "experiment manifest is required to register",
                code=BacktestErrorCode.CATALOG_INVALID,
            )
        register_backtest_experiment(session, written.manifest)
    return written


def _member_usable(
    session: Session,
    manifest: BacktestManifest,
    member_dir: Path,
    *,
    register: bool,
    research_mode: bool,
) -> bool:
    if register:
        register_backtest_run(session, manifest)
        session.flush()
        report = evaluate_backtest_result_usability(
            session,
            str(manifest.backtest_id),
            member_dir,
            research_mode=research_mode,
        )
        return report.usable_result
    local = verify_backtest_artifacts(member_dir)
    return local.ok and backtest_run_is_usable(manifest)


def _member_hash_payload(
    item: BacktestExperimentMember | Mapping[str, object],
) -> dict[str, object]:
    if isinstance(item, BacktestExperimentMember):
        return item.hash_mapping()
    config = item.get("policy_config")
    return {
        "replay_id": item.get("replay_id"),
        "stream_hash": item.get("stream_hash"),
        "backtest_hash": item.get("backtest_hash"),
        "policy_name": item.get("policy_name"),
        "policy_config": dict(config) if isinstance(config, dict) else {},
        "usable_result": bool(item.get("usable_result")),
        "warning_count": _as_count(item.get("warning_count")),
        "error_count": _as_count(item.get("error_count")),
    }


def _as_count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value


def members_from_experiment_summary(
    summary: Mapping[str, object],
) -> tuple[BacktestExperimentMember, ...]:
    raw = summary.get("members")
    if not isinstance(raw, list):
        return ()
    members: list[BacktestExperimentMember] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        config = item.get("policy_config")
        members.append(
            BacktestExperimentMember(
                replay_id=str(item.get("replay_id") or ""),
                backtest_id=str(item.get("backtest_id") or ""),
                stream_hash=str(item.get("stream_hash") or ""),
                backtest_hash=str(item.get("backtest_hash") or ""),
                policy_name=str(item.get("policy_name") or ""),
                policy_config=dict(config) if isinstance(config, dict) else {},
                usable_result=bool(item.get("usable_result")),
                warning_count=int(item.get("warning_count") or 0),
                error_count=int(item.get("error_count") or 0),
                relative_path=str(item.get("relative_path") or ""),
            )
        )
    return tuple(members)
