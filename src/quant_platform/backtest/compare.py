"""Deep backtest-run comparison. Metadata only; no event rows or PnL."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy.orm import Session

from quant_platform.backtest.catalog import get_backtest_run_by_id
from quant_platform.backtest.errors import BacktestError, BacktestErrorCode
from quant_platform.backtest.types import BacktestManifest, BacktestRunCatalogEntry
from quant_platform.research.snapshots import canonical_json

DIFF_KIND = "backtest_run_diff"
DIFF_FORMAT_VERSION = 1


class BacktestRunDiffVerdict(StrEnum):
    IDENTICAL = "identical"
    SAME_RESULT = "same_result"
    DIFFERENT = "different"


@dataclass(frozen=True, slots=True)
class BacktestRunDiffItem:
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
class BacktestRunDiff:
    backtest_a_id: str
    backtest_b_id: str
    same_backtest_hash: bool
    same_manifest_hash: bool
    same_replay_id: bool
    same_stream_hash: bool
    same_policy_name: bool
    identical: bool
    verdict: str
    items: tuple[BacktestRunDiffItem, ...]

    def as_mapping(self) -> dict[str, object]:
        return {
            "kind": DIFF_KIND,
            "format_version": DIFF_FORMAT_VERSION,
            "backtest_a_id": self.backtest_a_id,
            "backtest_b_id": self.backtest_b_id,
            "same_backtest_hash": self.same_backtest_hash,
            "same_manifest_hash": self.same_manifest_hash,
            "same_replay_id": self.same_replay_id,
            "same_stream_hash": self.same_stream_hash,
            "same_policy_name": self.same_policy_name,
            "identical": self.identical,
            "verdict": self.verdict,
            "items": [item.as_mapping() for item in self.items],
        }


def diff_backtest_runs(
    run_a: BacktestRunCatalogEntry | BacktestManifest,
    run_b: BacktestRunCatalogEntry | BacktestManifest,
) -> BacktestRunDiff:
    """Compare catalog/manifest metadata. Does not load replay events."""
    left = _view(run_a)
    right = _view(run_b)
    items: list[BacktestRunDiffItem] = []
    _add(
        items,
        "backtest_hash",
        left.backtest_hash,
        right.backtest_hash,
        "backtest_hash_diff",
    )
    _add(
        items,
        "manifest_hash",
        left.manifest_hash,
        right.manifest_hash,
        "manifest_hash_diff",
    )
    _add(items, "replay_id", left.replay_id, right.replay_id, "replay_id_diff")
    _add(items, "stream_hash", left.stream_hash, right.stream_hash, "stream_hash_diff")
    _add(items, "policy_name", left.policy_name, right.policy_name, "policy_name_diff")
    _add(items, "event_count", left.event_count, right.event_count, "event_count_diff")
    _add(
        items,
        "market_event_count",
        left.market_event_count,
        right.market_event_count,
        "event_count_diff",
    )
    _add(
        items,
        "session_event_count",
        left.session_event_count,
        right.session_event_count,
        "event_count_diff",
    )
    _add(
        items,
        "corporate_action_event_count",
        left.corporate_action_event_count,
        right.corporate_action_event_count,
        "event_count_diff",
    )
    _add(
        items,
        "warning_count",
        left.warning_count,
        right.warning_count,
        "event_count_diff",
    )
    _add(items, "error_count", left.error_count, right.error_count, "event_count_diff")
    _add(
        items,
        "package_version",
        left.package_version,
        right.package_version,
        "package_version_diff",
    )
    _add(items, "git_commit", left.git_commit, right.git_commit, "git_commit_diff")
    _add(items, "artifacts", left.artifacts, right.artifacts, "artifact_diff")
    _add(items, "notes", left.notes, right.notes, "notes_diff")
    ranked = tuple(sorted(items, key=lambda item: (item.field, item.code)))
    same_hash = left.backtest_hash == right.backtest_hash
    same_manifest = left.manifest_hash == right.manifest_hash
    if same_manifest:
        verdict = BacktestRunDiffVerdict.IDENTICAL.value
    elif same_hash:
        verdict = BacktestRunDiffVerdict.SAME_RESULT.value
    else:
        verdict = BacktestRunDiffVerdict.DIFFERENT.value
    return BacktestRunDiff(
        backtest_a_id=left.backtest_id,
        backtest_b_id=right.backtest_id,
        same_backtest_hash=same_hash,
        same_manifest_hash=same_manifest,
        same_replay_id=left.replay_id == right.replay_id,
        same_stream_hash=left.stream_hash == right.stream_hash,
        same_policy_name=left.policy_name == right.policy_name,
        identical=same_manifest,
        verdict=verdict,
        items=ranked,
    )


def diff_catalog_backtest_runs(
    session: Session, backtest_id_a: str, backtest_id_b: str
) -> BacktestRunDiff:
    left = get_backtest_run_by_id(session, backtest_id_a)
    right = get_backtest_run_by_id(session, backtest_id_b)
    if left is None or right is None:
        raise BacktestError(
            "both backtest_id values must exist in the catalog",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    return diff_backtest_runs(left, right)


def backtest_run_diff_json(diff: BacktestRunDiff) -> str:
    return canonical_json(diff.as_mapping())


@dataclass(frozen=True, slots=True)
class _DiffView:
    backtest_id: str
    replay_id: str
    stream_hash: str
    backtest_hash: str
    manifest_hash: str
    policy_name: str
    event_count: str
    market_event_count: str
    session_event_count: str
    corporate_action_event_count: str
    warning_count: str
    error_count: str
    package_version: str
    git_commit: str | None
    artifacts: str
    notes: str | None


def _view(item: BacktestRunCatalogEntry | BacktestManifest) -> _DiffView:
    if isinstance(item, BacktestManifest):
        return _view_manifest(item)
    return _view_entry(item)


def _view_manifest(item: BacktestManifest) -> _DiffView:
    paths = tuple(sorted(artifact.path for artifact in item.artifacts))
    return _DiffView(
        backtest_id=str(item.backtest_id),
        replay_id=item.replay_id,
        stream_hash=item.stream_hash,
        backtest_hash=item.backtest_hash,
        manifest_hash=item.manifest_hash,
        policy_name=item.policy_name,
        event_count=str(_summary_int(item.summary, "event_count")),
        market_event_count=str(_summary_int(item.summary, "market_event_count")),
        session_event_count=str(_summary_int(item.summary, "session_event_count")),
        corporate_action_event_count=str(
            _summary_int(item.summary, "corporate_action_event_count")
        ),
        warning_count=str(_summary_int(item.summary, "warning_count")),
        error_count=str(_summary_int(item.summary, "error_count")),
        package_version=item.package_version,
        git_commit=item.git_commit,
        artifacts=canonical_json(list(paths)),
        notes=item.notes,
    )


def _view_entry(item: BacktestRunCatalogEntry) -> _DiffView:
    paths: list[str] = []
    for artifact in item.artifacts:
        path = artifact.get("path")
        if isinstance(path, str):
            paths.append(path)
    return _DiffView(
        backtest_id=item.backtest_id,
        replay_id=item.replay_id,
        stream_hash=item.stream_hash,
        backtest_hash=item.backtest_hash,
        manifest_hash=item.manifest_hash,
        policy_name=item.policy_name,
        event_count=str(item.event_count),
        market_event_count=str(item.market_event_count),
        session_event_count=str(item.session_event_count),
        corporate_action_event_count=str(item.corporate_action_event_count),
        warning_count=str(item.warning_count),
        error_count=str(item.error_count),
        package_version=item.package_version,
        git_commit=item.git_commit,
        artifacts=canonical_json(sorted(paths)),
        notes=item.notes,
    )


def _summary_int(summary: dict[str, object], field: str) -> int:
    raw = summary.get(field, 0)
    if isinstance(raw, bool) or not isinstance(raw, int):
        return 0
    return raw


def _add(
    items: list[BacktestRunDiffItem],
    field: str,
    left: str | None,
    right: str | None,
    code: str,
) -> None:
    if left != right:
        items.append(
            BacktestRunDiffItem(field=field, code=code, left=left, right=right)
        )
