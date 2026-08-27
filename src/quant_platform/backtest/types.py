"""Typed backtest shapes. Counts and hashes only; no portfolio or PnL."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from quant_platform.backtest.errors import BacktestError, BacktestErrorCode
from quant_platform.backtest.observations import normalize_policy_config
from quant_platform.research.snapshots import canonical_datetime
from quant_platform.simulation.run_types import artifact_path_is_unsafe

if TYPE_CHECKING:
    from quant_platform.backtest.observations import PolicyRunOutput

BACKTEST_KIND = "backtest_run"
BACKTEST_FORMAT_VERSION = 2
BACKTEST_HASH_KIND = "backtest_result"
BACKTEST_HASH_FORMAT_VERSION = 2

NOOP_POLICY_NAME = "noop"
EVENT_COUNTING_POLICY_NAME = "event_counting"
DATA_QUALITY_POLICY_NAME = "data_quality"
COVERAGE_POLICY_NAME = "coverage"
CORPORATE_ACTION_AUDIT_POLICY_NAME = "corporate_action_audit"
CORRECTION_AUDIT_POLICY_NAME = "correction_audit"
ALLOWED_POLICY_NAMES = frozenset(
    {
        NOOP_POLICY_NAME,
        EVENT_COUNTING_POLICY_NAME,
        DATA_QUALITY_POLICY_NAME,
        COVERAGE_POLICY_NAME,
        CORPORATE_ACTION_AUDIT_POLICY_NAME,
        CORRECTION_AUDIT_POLICY_NAME,
    }
)

SUMMARY_ARTIFACT_NAME = "summary.json"
MANIFEST_ARTIFACT_NAME = "manifest.json"
POLICY_OUTPUT_ARTIFACT_NAME = "policy_output.json"


def optional_backtest_notes(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def artifacts_have_unsafe_paths(artifacts: Sequence[Mapping[str, object]]) -> bool:
    return any(_artifact_mapping_is_unsafe(item) for item in artifacts)


def _artifact_mapping_is_unsafe(item: Mapping[str, object]) -> bool:
    path = item.get("path")
    if not isinstance(path, str):
        return True
    return artifact_path_is_unsafe(path)


@dataclass(frozen=True, slots=True)
class BacktestRequest:
    replay_id: str
    deterministic_id: bool = False
    policy_name: str = NOOP_POLICY_NAME
    policy_config: dict[str, object] | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        cleaned = self.replay_id.strip()
        if not cleaned:
            raise BacktestError(
                "replay_id must not be empty",
                code=BacktestErrorCode.CATALOG_INVALID,
            )
        object.__setattr__(self, "replay_id", cleaned)
        policy = self.policy_name.strip()
        if policy not in ALLOWED_POLICY_NAMES:
            raise BacktestError(
                "policy_name must be a registered research policy",
                code=BacktestErrorCode.INVALID_POLICY,
            )
        object.__setattr__(self, "policy_name", policy)
        object.__setattr__(
            self, "policy_config", normalize_policy_config(self.policy_config)
        )
        object.__setattr__(self, "notes", optional_backtest_notes(self.notes))

    def as_mapping(self) -> dict[str, object]:
        return {
            "replay_id": self.replay_id,
            "deterministic_id": self.deterministic_id,
            "policy_name": self.policy_name,
            "policy_config": dict(self.policy_config or {}),
            "notes": self.notes,
        }


@dataclass(frozen=True, slots=True)
class BacktestArtifact:
    name: str
    path: str
    kind: str

    def as_mapping(self) -> dict[str, object]:
        if artifact_path_is_unsafe(self.path):
            raise BacktestError(
                "backtest artifact paths must be relative",
                code=BacktestErrorCode.CATALOG_INVALID,
            )
        return {"name": self.name, "path": self.path, "kind": self.kind}


def default_backtest_artifacts() -> tuple[BacktestArtifact, ...]:
    return (
        BacktestArtifact(name="summary", path=SUMMARY_ARTIFACT_NAME, kind="json"),
        BacktestArtifact(name="manifest", path=MANIFEST_ARTIFACT_NAME, kind="json"),
        BacktestArtifact(
            name="policy_output", path=POLICY_OUTPUT_ARTIFACT_NAME, kind="json"
        ),
    )


@dataclass(frozen=True, slots=True)
class BacktestSummary:
    backtest_id: UUID
    replay_id: str
    stream_hash: str
    backtest_hash: str
    policy_name: str
    policy_config: dict[str, object]
    policy_output_hash: str
    event_count: int
    market_event_count: int
    session_event_count: int
    corporate_action_event_count: int
    started_event_seen: bool
    finished_event_seen: bool
    warning_count: int
    error_count: int
    warnings: tuple[str, ...]
    errors: tuple[str, ...]

    def as_mapping(self) -> dict[str, object]:
        return {
            "backtest_id": str(self.backtest_id),
            "replay_id": self.replay_id,
            "stream_hash": self.stream_hash,
            "backtest_hash": self.backtest_hash,
            "policy_name": self.policy_name,
            "policy_config": dict(self.policy_config),
            "policy_output_hash": self.policy_output_hash,
            "event_count": self.event_count,
            "market_event_count": self.market_event_count,
            "session_event_count": self.session_event_count,
            "corporate_action_event_count": self.corporate_action_event_count,
            "started_event_seen": self.started_event_seen,
            "finished_event_seen": self.finished_event_seen,
            "warning_count": self.warning_count,
            "error_count": self.error_count,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


@dataclass(frozen=True, slots=True)
class BacktestManifest:
    backtest_id: UUID
    created_at: datetime
    package_version: str
    git_commit: str | None
    replay_id: str
    stream_hash: str
    backtest_hash: str
    policy_name: str
    policy_config: dict[str, object]
    policy_output_hash: str
    request: dict[str, object]
    summary: dict[str, object]
    artifacts: tuple[BacktestArtifact, ...]
    notes: str | None
    manifest_hash: str

    def as_mapping(self, *, include_manifest_hash: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "kind": BACKTEST_KIND,
            "format_version": BACKTEST_FORMAT_VERSION,
            "backtest_id": str(self.backtest_id),
            "created_at": canonical_datetime(self.created_at),
            "package_version": self.package_version,
            "git_commit": self.git_commit,
            "replay_id": self.replay_id,
            "stream_hash": self.stream_hash,
            "backtest_hash": self.backtest_hash,
            "policy_name": self.policy_name,
            "policy_config": dict(self.policy_config),
            "policy_output_hash": self.policy_output_hash,
            "request": dict(self.request),
            "summary": dict(self.summary),
            "artifacts": [item.as_mapping() for item in self.artifacts],
            "notes": self.notes,
        }
        if include_manifest_hash:
            payload["manifest_hash"] = self.manifest_hash
        return payload


@dataclass(frozen=True, slots=True)
class BacktestResult:
    request: BacktestRequest
    summary: BacktestSummary
    policy_output: PolicyRunOutput | None = None
    manifest: BacktestManifest | None = None
    output_dir: Path | None = None
    orders: tuple[object, ...] = ()
    fills: tuple[object, ...] = ()
    signals: tuple[object, ...] = ()


@dataclass(frozen=True, slots=True)
class BacktestRunCatalogEntry:
    backtest_id: str
    replay_id: str
    stream_hash: str
    backtest_hash: str
    manifest_hash: str
    policy_name: str
    policy_config: dict[str, object]
    policy_output_hash: str | None
    package_version: str
    git_commit: str | None
    created_at: datetime
    event_count: int
    market_event_count: int
    session_event_count: int
    corporate_action_event_count: int
    warning_count: int
    error_count: int
    is_reproducible: bool
    is_usable: bool
    request: dict[str, object]
    summary: dict[str, object]
    artifacts: tuple[dict[str, object], ...]
    notes: str | None
    registered_at: datetime

    def as_mapping(self) -> dict[str, object]:
        return {
            "backtest_id": self.backtest_id,
            "replay_id": self.replay_id,
            "stream_hash": self.stream_hash,
            "backtest_hash": self.backtest_hash,
            "manifest_hash": self.manifest_hash,
            "policy_name": self.policy_name,
            "policy_config": dict(self.policy_config),
            "policy_output_hash": self.policy_output_hash,
            "package_version": self.package_version,
            "git_commit": self.git_commit,
            "created_at": self.created_at.isoformat(),
            "event_count": self.event_count,
            "market_event_count": self.market_event_count,
            "session_event_count": self.session_event_count,
            "corporate_action_event_count": self.corporate_action_event_count,
            "warning_count": self.warning_count,
            "error_count": self.error_count,
            "is_reproducible": self.is_reproducible,
            "is_usable": self.is_usable,
            "request": dict(self.request),
            "summary": dict(self.summary),
            "artifacts": [dict(item) for item in self.artifacts],
            "notes": self.notes,
            "registered_at": self.registered_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class BacktestRunComparison:
    backtest_a_id: str
    backtest_b_id: str
    same_backtest_hash: bool
    same_stream_hash: bool
    same_replay_id: bool
    same_policy_name: bool
    same_policy_output_hash: bool
    same_manifest_hash: bool
    event_count_delta: int
    warning_count_delta: int
    error_count_delta: int
    differences: tuple[str, ...]

    def as_mapping(self) -> dict[str, object]:
        return {
            "backtest_a_id": self.backtest_a_id,
            "backtest_b_id": self.backtest_b_id,
            "same_backtest_hash": self.same_backtest_hash,
            "same_stream_hash": self.same_stream_hash,
            "same_replay_id": self.same_replay_id,
            "same_policy_name": self.same_policy_name,
            "same_policy_output_hash": self.same_policy_output_hash,
            "same_manifest_hash": self.same_manifest_hash,
            "event_count_delta": self.event_count_delta,
            "warning_count_delta": self.warning_count_delta,
            "error_count_delta": self.error_count_delta,
            "differences": list(self.differences),
        }


@dataclass(frozen=True, slots=True)
class BacktestRunRegistration:
    entry: BacktestRunCatalogEntry
    action: str


@dataclass(frozen=True, slots=True)
class BacktestRunCatalogFilters:
    replay_id: str | None = None
    stream_hash: str | None = None
    usable_only: bool = False
    policy_name: str | None = None


def build_backtest_run_catalog_filters(
    *,
    replay_id: str | None = None,
    stream_hash: str | None = None,
    usable_only: bool = False,
    policy_name: str | None = None,
) -> BacktestRunCatalogFilters:
    cleaned_policy = _optional_token(policy_name, field="policy_name")
    if cleaned_policy is not None and cleaned_policy not in ALLOWED_POLICY_NAMES:
        raise BacktestError(
            "policy_name must be a registered research policy",
            code=BacktestErrorCode.INVALID_POLICY,
        )
    return BacktestRunCatalogFilters(
        replay_id=_optional_token(replay_id, field="replay_id"),
        stream_hash=_optional_token(stream_hash, field="stream_hash"),
        usable_only=usable_only,
        policy_name=cleaned_policy,
    )


def _optional_token(value: str | None, *, field: str) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        raise BacktestError(
            f"{field} must not be empty",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    return stripped
