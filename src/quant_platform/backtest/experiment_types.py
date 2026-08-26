"""Typed backtest-experiment shapes. Metadata only; not a strategy or PnL."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from uuid import UUID

from quant_platform.backtest.errors import BacktestError, BacktestErrorCode
from quant_platform.backtest.observations import (
    contains_operative_language,
    normalize_policy_config,
)
from quant_platform.backtest.types import (
    ALLOWED_POLICY_NAMES,
    optional_backtest_notes,
)
from quant_platform.research.snapshots import canonical_datetime, canonical_json
from quant_platform.simulation.run_types import artifact_path_is_unsafe

EXPERIMENT_KIND = "backtest_experiment"
EXPERIMENT_FORMAT_VERSION = 1
EXPERIMENT_HASH_KIND = "backtest_experiment"
EXPERIMENT_HASH_FORMAT_VERSION = 1

EXPERIMENT_SUMMARY_ARTIFACT_NAME = "experiment_summary.json"
EXPERIMENT_MANIFEST_ARTIFACT_NAME = "experiment_manifest.json"
EXPERIMENT_RUNS_DIRNAME = "runs"

EXPERIMENT_VERDICT_IDENTICAL = "identical"
EXPERIMENT_VERDICT_SAME_RESULT = "same_result"
EXPERIMENT_VERDICT_DIFFERENT = "different"


def _normalize_replay_ids(values: Sequence[str]) -> tuple[str, ...]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in values:
        item = raw.strip()
        if not item:
            raise BacktestError(
                "replay_ids must not contain empty values",
                code=BacktestErrorCode.CATALOG_INVALID,
            )
        if item in seen:
            continue
        seen.add(item)
        cleaned.append(item)
    if not cleaned:
        raise BacktestError(
            "replay_ids must not be empty",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    return tuple(cleaned)


def _normalize_policy_configs(
    values: Sequence[Mapping[str, object]] | None,
) -> tuple[dict[str, object], ...]:
    if values is None or len(values) == 0:
        return ({},)
    configs: list[dict[str, object]] = []
    for item in values:
        configs.append(normalize_policy_config(item))
    return tuple(configs)


@dataclass(frozen=True, slots=True)
class BacktestExperimentRequest:
    experiment_name: str
    replay_ids: tuple[str, ...]
    policy_name: str
    description: str | None = None
    policy_configs: tuple[dict[str, object], ...] = field(default_factory=tuple)
    deterministic_ids: bool = False
    notes: str | None = None

    def __post_init__(self) -> None:
        name = self.experiment_name.strip()
        if not name:
            raise BacktestError(
                "experiment_name must not be empty",
                code=BacktestErrorCode.CATALOG_INVALID,
            )
        object.__setattr__(self, "experiment_name", name)
        object.__setattr__(self, "replay_ids", _normalize_replay_ids(self.replay_ids))
        policy = self.policy_name.strip()
        if policy not in ALLOWED_POLICY_NAMES:
            raise BacktestError(
                "policy_name must be a registered research policy",
                code=BacktestErrorCode.INVALID_POLICY,
            )
        object.__setattr__(self, "policy_name", policy)
        object.__setattr__(
            self, "policy_configs", _normalize_policy_configs(self.policy_configs)
        )
        object.__setattr__(
            self, "description", optional_backtest_notes(self.description)
        )
        object.__setattr__(self, "notes", optional_backtest_notes(self.notes))
        blob = canonical_json(self.as_mapping())
        if contains_operative_language(blob):
            raise BacktestError(
                "experiment request must not contain investment-decision wording",
                code=BacktestErrorCode.INVALID_POLICY,
            )

    def as_mapping(self) -> dict[str, object]:
        return {
            "experiment_name": self.experiment_name,
            "description": self.description,
            "replay_ids": list(self.replay_ids),
            "policy_name": self.policy_name,
            "policy_configs": [dict(item) for item in self.policy_configs],
            "deterministic_ids": self.deterministic_ids,
            "notes": self.notes,
        }


@dataclass(frozen=True, slots=True)
class BacktestExperimentMember:
    replay_id: str
    backtest_id: str
    stream_hash: str
    backtest_hash: str
    policy_name: str
    policy_config: dict[str, object]
    usable_result: bool
    warning_count: int
    error_count: int
    relative_path: str = ""

    def __post_init__(self) -> None:
        if self.relative_path and artifact_path_is_unsafe(self.relative_path):
            raise BacktestError(
                "experiment member paths must be relative",
                code=BacktestErrorCode.CATALOG_INVALID,
            )
        if self.warning_count < 0 or self.error_count < 0:
            raise BacktestError(
                "member warning_count and error_count must be >= 0",
                code=BacktestErrorCode.CATALOG_INVALID,
            )

    def as_mapping(self) -> dict[str, object]:
        payload: dict[str, object] = {
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
        if self.relative_path:
            payload["relative_path"] = self.relative_path
        return payload

    def hash_mapping(self) -> dict[str, object]:
        """Stable member payload for experiment_hash. No paths."""
        return {
            "replay_id": self.replay_id,
            "stream_hash": self.stream_hash,
            "backtest_hash": self.backtest_hash,
            "policy_name": self.policy_name,
            "policy_config": dict(self.policy_config),
            "usable_result": self.usable_result,
            "warning_count": self.warning_count,
            "error_count": self.error_count,
        }


@dataclass(frozen=True, slots=True)
class BacktestExperimentArtifact:
    name: str
    path: str
    kind: str

    def as_mapping(self) -> dict[str, object]:
        if artifact_path_is_unsafe(self.path):
            raise BacktestError(
                "experiment artifact paths must be relative",
                code=BacktestErrorCode.CATALOG_INVALID,
            )
        return {"name": self.name, "path": self.path, "kind": self.kind}


def default_experiment_artifacts(
    members: Sequence[BacktestExperimentMember],
) -> tuple[BacktestExperimentArtifact, ...]:
    items = [
        BacktestExperimentArtifact(
            name="summary", path=EXPERIMENT_SUMMARY_ARTIFACT_NAME, kind="json"
        ),
        BacktestExperimentArtifact(
            name="manifest", path=EXPERIMENT_MANIFEST_ARTIFACT_NAME, kind="json"
        ),
    ]
    for index, member in enumerate(members, start=1):
        relative = member.relative_path or f"{EXPERIMENT_RUNS_DIRNAME}/{index:04d}"
        items.append(
            BacktestExperimentArtifact(
                name=f"member_{index:04d}",
                path=f"{relative}/manifest.json",
                kind="json",
            )
        )
    return tuple(items)


@dataclass(frozen=True, slots=True)
class BacktestExperimentSummary:
    experiment_id: str
    experiment_name: str
    experiment_hash: str
    policy_name: str
    member_count: int
    usable_count: int
    error_count: int
    warning_count: int
    replay_ids: tuple[str, ...]
    policy_configs: tuple[dict[str, object], ...]
    members: tuple[BacktestExperimentMember, ...]

    def as_mapping(self) -> dict[str, object]:
        return {
            "experiment_id": self.experiment_id,
            "experiment_name": self.experiment_name,
            "experiment_hash": self.experiment_hash,
            "policy_name": self.policy_name,
            "member_count": self.member_count,
            "usable_count": self.usable_count,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "replay_ids": list(self.replay_ids),
            "policy_configs": [dict(item) for item in self.policy_configs],
            "members": [item.as_mapping() for item in self.members],
        }


@dataclass(frozen=True, slots=True)
class BacktestExperimentManifest:
    experiment_id: str
    created_at: datetime
    package_version: str
    git_commit: str | None
    experiment_name: str
    description: str | None
    experiment_hash: str
    policy_name: str
    request: dict[str, object]
    summary: dict[str, object]
    artifacts: tuple[BacktestExperimentArtifact, ...]
    notes: str | None
    manifest_hash: str

    def as_mapping(self, *, include_manifest_hash: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "kind": EXPERIMENT_KIND,
            "format_version": EXPERIMENT_FORMAT_VERSION,
            "experiment_id": self.experiment_id,
            "created_at": canonical_datetime(self.created_at),
            "package_version": self.package_version,
            "git_commit": self.git_commit,
            "experiment_name": self.experiment_name,
            "description": self.description,
            "experiment_hash": self.experiment_hash,
            "policy_name": self.policy_name,
            "request": dict(self.request),
            "summary": dict(self.summary),
            "artifacts": [item.as_mapping() for item in self.artifacts],
            "notes": self.notes,
        }
        if include_manifest_hash:
            payload["manifest_hash"] = self.manifest_hash
        return payload


@dataclass(frozen=True, slots=True)
class BacktestExperimentResult:
    request: BacktestExperimentRequest
    summary: BacktestExperimentSummary
    members: tuple[BacktestExperimentMember, ...]
    manifest: BacktestExperimentManifest | None = None
    output_dir: Path | None = None


@dataclass(frozen=True, slots=True)
class BacktestExperimentComparisonItem:
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
class BacktestExperimentComparison:
    experiment_a_id: str
    experiment_b_id: str
    same_experiment_hash: bool
    same_manifest_hash: bool
    identical: bool
    verdict: str
    items: tuple[BacktestExperimentComparisonItem, ...]

    def as_mapping(self) -> dict[str, object]:
        return {
            "kind": "backtest_experiment_diff",
            "format_version": 1,
            "experiment_a_id": self.experiment_a_id,
            "experiment_b_id": self.experiment_b_id,
            "same_experiment_hash": self.same_experiment_hash,
            "same_manifest_hash": self.same_manifest_hash,
            "identical": self.identical,
            "verdict": self.verdict,
            "items": [item.as_mapping() for item in self.items],
        }


@dataclass(frozen=True, slots=True)
class BacktestExperimentCatalogEntry:
    experiment_id: str
    experiment_name: str
    experiment_hash: str
    manifest_hash: str
    policy_name: str
    package_version: str
    git_commit: str | None
    created_at: datetime
    member_count: int
    usable_count: int
    error_count: int
    warning_count: int
    request: dict[str, object]
    summary: dict[str, object]
    artifacts: tuple[dict[str, object], ...]
    notes: str | None
    registered_at: datetime

    def as_mapping(self) -> dict[str, object]:
        return {
            "experiment_id": self.experiment_id,
            "experiment_name": self.experiment_name,
            "experiment_hash": self.experiment_hash,
            "manifest_hash": self.manifest_hash,
            "policy_name": self.policy_name,
            "package_version": self.package_version,
            "git_commit": self.git_commit,
            "created_at": canonical_datetime(self.created_at),
            "member_count": self.member_count,
            "usable_count": self.usable_count,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "request": dict(self.request),
            "summary": dict(self.summary),
            "artifacts": [dict(item) for item in self.artifacts],
            "notes": self.notes,
            "registered_at": canonical_datetime(self.registered_at),
        }


@dataclass(frozen=True, slots=True)
class BacktestExperimentRegistration:
    entry: BacktestExperimentCatalogEntry
    action: str


@dataclass(frozen=True, slots=True)
class BacktestExperimentCatalogFilters:
    experiment_name: str | None = None
    policy_name: str | None = None
    usable_only: bool = False


def build_backtest_experiment_catalog_filters(
    *,
    experiment_name: str | None = None,
    policy_name: str | None = None,
    usable_only: bool = False,
) -> BacktestExperimentCatalogFilters:
    name = None if experiment_name is None else experiment_name.strip() or None
    policy = None if policy_name is None else policy_name.strip() or None
    if policy is not None and policy not in ALLOWED_POLICY_NAMES:
        raise BacktestError(
            "policy_name must be a registered research policy",
            code=BacktestErrorCode.INVALID_POLICY,
        )
    return BacktestExperimentCatalogFilters(
        experiment_name=name,
        policy_name=policy,
        usable_only=usable_only,
    )


def member_relative_path(index: int) -> str:
    return f"{EXPERIMENT_RUNS_DIRNAME}/{index:04d}"


def experiment_id_from_uuid(value: UUID) -> str:
    return str(value)
