"""Deep replay-run comparison. Metadata only; does not read event rows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from quant_platform.research.snapshots import canonical_datetime, canonical_json
from quant_platform.simulation.errors import SimulationError, SimulationErrorCode
from quant_platform.simulation.readiness_types import (
    ReplayRunDiff,
    ReplayRunDiffItem,
    ReplayRunDiffVerdict,
    ReplayRunReadinessCode,
)
from quant_platform.simulation.run_catalog import get_replay_run_by_id
from quant_platform.simulation.run_types import ReplayRunCatalogEntry, ReplayRunManifest

_COUNT_CODE = ReplayRunReadinessCode.EVENT_COUNT_DIFF.value


def diff_replay_runs(
    run_a: ReplayRunCatalogEntry | ReplayRunManifest,
    run_b: ReplayRunCatalogEntry | ReplayRunManifest,
) -> ReplayRunDiff:
    """Compare catalog metadata. Does not load ``events.jsonl``."""
    left = _view(run_a)
    right = _view(run_b)
    items: list[ReplayRunDiffItem] = []
    _add(
        items,
        "stream_hash",
        left.stream_hash,
        right.stream_hash,
        ReplayRunReadinessCode.STREAM_HASH_DIFF.value,
    )
    _add(
        items,
        "manifest_hash",
        left.manifest_hash,
        right.manifest_hash,
        ReplayRunReadinessCode.MANIFEST_HASH_DIFF.value,
    )
    _add(items, "source_type", left.source_type, right.source_type, "source_type_diff")
    _add(
        items,
        "dataset_snapshot_id",
        left.dataset_snapshot_id,
        right.dataset_snapshot_id,
        "dataset_snapshot_id_diff",
    )
    _add(
        items,
        "dataset_content_hash",
        left.dataset_content_hash,
        right.dataset_content_hash,
        "dataset_content_hash_diff",
    )
    _add(items, "event_count", left.event_count, right.event_count, _COUNT_CODE)
    _add(
        items,
        "event_counts_by_type",
        left.event_counts_by_type,
        right.event_counts_by_type,
        _COUNT_CODE,
    )
    _add(
        items,
        "pre_known_event_count",
        left.pre_known_event_count,
        right.pre_known_event_count,
        _COUNT_CODE,
    )
    _add(
        items,
        "market_event_count",
        left.market_event_count,
        right.market_event_count,
        _COUNT_CODE,
    )
    _add(
        items,
        "session_event_count",
        left.session_event_count,
        right.session_event_count,
        _COUNT_CODE,
    )
    _add(
        items,
        "corporate_action_event_count",
        left.corporate_action_event_count,
        right.corporate_action_event_count,
        _COUNT_CODE,
    )
    _add(items, "boundary_ok", left.boundary_ok, right.boundary_ok, "boundary_diff")
    _add(items, "warning_count", left.warning_count, right.warning_count, _COUNT_CODE)
    _add(items, "error_count", left.error_count, right.error_count, _COUNT_CODE)
    _add(
        items,
        "first_event_time",
        left.first_event_time,
        right.first_event_time,
        "event_time_diff",
    )
    _add(
        items,
        "last_event_time",
        left.last_event_time,
        right.last_event_time,
        "event_time_diff",
    )
    _add(
        items,
        "first_market_event_time",
        left.first_market_event_time,
        right.first_market_event_time,
        "event_time_diff",
    )
    _add(
        items,
        "last_market_event_time",
        left.last_market_event_time,
        right.last_market_event_time,
        "event_time_diff",
    )
    _add(items, "git_commit", left.git_commit, right.git_commit, "git_commit_diff")
    _add(
        items,
        "package_version",
        left.package_version,
        right.package_version,
        "package_version_diff",
    )
    _add(items, "artifacts", left.artifacts, right.artifacts, "artifact_diff")
    _add(items, "notes", left.notes, right.notes, "notes_diff")
    ranked = tuple(sorted(items, key=lambda item: (item.field, item.code)))
    same_stream = left.stream_hash == right.stream_hash
    same_manifest = left.manifest_hash == right.manifest_hash
    identical = len(ranked) == 0
    if identical:
        verdict = ReplayRunDiffVerdict.IDENTICAL.value
    elif same_stream:
        verdict = ReplayRunDiffVerdict.SAME_STREAM.value
    else:
        verdict = ReplayRunDiffVerdict.DIFFERENT.value
    return ReplayRunDiff(
        replay_a_id=left.replay_id,
        replay_b_id=right.replay_id,
        same_stream_hash=same_stream,
        same_manifest_hash=same_manifest,
        identical=identical,
        verdict=verdict,
        items=ranked,
    )


def diff_catalog_replay_runs(
    session: Session, replay_id_a: str, replay_id_b: str
) -> ReplayRunDiff:
    left = get_replay_run_by_id(session, replay_id_a)
    right = get_replay_run_by_id(session, replay_id_b)
    if left is None or right is None:
        raise SimulationError(
            "both replay_id values must exist in the catalog",
            code=SimulationErrorCode.CATALOG_INVALID,
        )
    return diff_replay_runs(left, right)


def replay_run_diff_json(diff: ReplayRunDiff) -> str:
    return canonical_json(diff.as_mapping())


@dataclass(frozen=True, slots=True)
class _DiffView:
    replay_id: str
    stream_hash: str
    manifest_hash: str
    source_type: str
    dataset_snapshot_id: str | None
    dataset_content_hash: str | None
    event_count: str
    event_counts_by_type: str
    pre_known_event_count: str
    market_event_count: str
    session_event_count: str
    corporate_action_event_count: str
    boundary_ok: str
    warning_count: str
    error_count: str
    first_event_time: str | None
    last_event_time: str | None
    first_market_event_time: str | None
    last_market_event_time: str | None
    git_commit: str | None
    package_version: str
    artifacts: str
    notes: str | None


def _view(item: ReplayRunCatalogEntry | ReplayRunManifest) -> _DiffView:
    if isinstance(item, ReplayRunManifest):
        return _view_manifest(item)
    return _view_entry(item)


def _view_manifest(item: ReplayRunManifest) -> _DiffView:
    counts = {
        key: item.event_counts_by_type[key] for key in sorted(item.event_counts_by_type)
    }
    paths = tuple(sorted(artifact.path for artifact in item.artifacts))
    return _DiffView(
        replay_id=str(item.replay_id),
        stream_hash=item.stream_hash,
        manifest_hash=item.manifest_hash,
        source_type=item.source_type,
        dataset_snapshot_id=item.dataset_snapshot_id,
        dataset_content_hash=item.dataset_content_hash,
        event_count=str(item.event_count),
        event_counts_by_type=canonical_json(counts),
        pre_known_event_count=str(item.pre_known_event_count),
        market_event_count=str(counts.get("market_bar", 0)),
        session_event_count=str(counts.get("market_session", 0)),
        corporate_action_event_count=str(counts.get("corporate_action", 0)),
        boundary_ok=str(item.boundary_ok).lower(),
        warning_count=str(item.warning_count),
        error_count=str(item.error_count),
        first_event_time=_fmt_time(item.first_event_time),
        last_event_time=_fmt_time(item.last_event_time),
        first_market_event_time=_fmt_time(item.first_market_event_time),
        last_market_event_time=_fmt_time(item.last_market_event_time),
        git_commit=item.git_commit,
        package_version=item.package_version,
        artifacts=canonical_json(list(paths)),
        notes=item.notes,
    )


def _view_entry(item: ReplayRunCatalogEntry) -> _DiffView:
    counts = _counts_from_audit(item.audit_summary)
    paths: list[str] = []
    for artifact in item.artifacts:
        path = artifact.get("path")
        if isinstance(path, str):
            paths.append(path)
    return _DiffView(
        replay_id=item.replay_id,
        stream_hash=item.stream_hash,
        manifest_hash=item.manifest_hash,
        source_type=item.source_type,
        dataset_snapshot_id=item.dataset_snapshot_id,
        dataset_content_hash=item.dataset_content_hash,
        event_count=str(item.event_count),
        event_counts_by_type=canonical_json(counts),
        pre_known_event_count=str(item.pre_known_event_count),
        market_event_count=str(item.market_event_count),
        session_event_count=str(item.session_event_count),
        corporate_action_event_count=str(item.corporate_action_event_count),
        boundary_ok=str(item.boundary_ok).lower(),
        warning_count=str(item.warning_count),
        error_count=str(item.error_count),
        first_event_time=None,
        last_event_time=None,
        first_market_event_time=None,
        last_market_event_time=None,
        git_commit=item.git_commit,
        package_version=item.package_version,
        artifacts=canonical_json(sorted(paths)),
        notes=item.notes,
    )


def _counts_from_audit(audit_summary: dict[str, object]) -> dict[str, int]:
    raw = audit_summary.get("counts_by_kind")
    if not isinstance(raw, dict):
        return {}
    counts: dict[str, int] = {}
    for key, value in raw.items():
        if (
            isinstance(key, str)
            and isinstance(value, int)
            and not isinstance(value, bool)
        ):
            counts[key] = value
    return {key: counts[key] for key in sorted(counts)}


def _fmt_time(value: datetime | None) -> str | None:
    if value is None:
        return None
    return canonical_datetime(value)


def _add(
    items: list[ReplayRunDiffItem],
    field: str,
    left: str | None,
    right: str | None,
    code: str,
) -> None:
    if left != right:
        items.append(ReplayRunDiffItem(field=field, code=code, left=left, right=right))
