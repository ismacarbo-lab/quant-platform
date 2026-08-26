"""Typed replay-run catalog shapes. Metadata only; not a backtest report."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import UUID

from quant_platform.research.snapshots import canonical_datetime
from quant_platform.simulation.errors import SimulationError, SimulationErrorCode
from quant_platform.simulation.summary import SOURCE_DATABASE, SOURCE_SNAPSHOT

REPLAY_RUN_KIND = "simulation_replay_run"
REPLAY_RUN_FORMAT_VERSION = 1

EVENTS_ARTIFACT_NAME = "events.jsonl"
AUDIT_ARTIFACT_NAME = "audit.json"
SUMMARY_ARTIFACT_NAME = "summary.json"
MANIFEST_ARTIFACT_NAME = "manifest.json"

SOURCE_TYPES = frozenset({SOURCE_DATABASE, SOURCE_SNAPSHOT})


def optional_replay_notes(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def artifact_path_is_unsafe(path: str) -> bool:
    """True when a stored path is absolute, empty, or escapes the run folder."""
    stripped = path.strip()
    if not stripped:
        return True
    candidate = Path(stripped)
    return candidate.is_absolute() or ".." in candidate.parts


def artifacts_have_unsafe_paths(artifacts: Sequence[Mapping[str, object]]) -> bool:
    return any(_artifact_mapping_is_unsafe(item) for item in artifacts)


def _artifact_mapping_is_unsafe(item: Mapping[str, object]) -> bool:
    path = item.get("path")
    if not isinstance(path, str):
        return True
    return artifact_path_is_unsafe(path)


@dataclass(frozen=True, slots=True)
class ReplayRunArtifact:
    name: str
    path: str
    kind: str

    def as_mapping(self) -> dict[str, object]:
        if artifact_path_is_unsafe(self.path):
            raise SimulationError(
                "replay artifact paths must be relative",
                code=SimulationErrorCode.CATALOG_INVALID,
            )
        return {"name": self.name, "path": self.path, "kind": self.kind}


def default_replay_run_artifacts() -> tuple[ReplayRunArtifact, ...]:
    return (
        ReplayRunArtifact(name="events", path=EVENTS_ARTIFACT_NAME, kind="jsonl"),
        ReplayRunArtifact(name="audit", path=AUDIT_ARTIFACT_NAME, kind="json"),
        ReplayRunArtifact(name="summary", path=SUMMARY_ARTIFACT_NAME, kind="json"),
        ReplayRunArtifact(name="manifest", path=MANIFEST_ARTIFACT_NAME, kind="json"),
    )


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return canonical_datetime(value)


@dataclass(frozen=True, slots=True)
class ReplayRunManifest:
    replay_id: UUID
    created_at: datetime
    package_version: str
    git_commit: str | None
    source_type: str
    dataset_snapshot_id: str | None
    dataset_content_hash: str | None
    stream_hash: str
    event_count: int
    event_counts_by_type: dict[str, int]
    pre_known_event_count: int
    boundary_ok: bool
    warning_count: int
    error_count: int
    first_event_time: datetime | None
    last_event_time: datetime | None
    first_market_event_time: datetime | None
    last_market_event_time: datetime | None
    request: dict[str, object]
    audit_summary: dict[str, object]
    artifacts: tuple[ReplayRunArtifact, ...]
    notes: str | None
    manifest_hash: str

    def as_mapping(self, *, include_manifest_hash: bool = True) -> dict[str, object]:
        counts = {
            key: self.event_counts_by_type[key]
            for key in sorted(self.event_counts_by_type)
        }
        payload: dict[str, object] = {
            "kind": REPLAY_RUN_KIND,
            "format_version": REPLAY_RUN_FORMAT_VERSION,
            "replay_id": str(self.replay_id),
            "created_at": canonical_datetime(self.created_at),
            "package_version": self.package_version,
            "git_commit": self.git_commit,
            "source_type": self.source_type,
            "dataset_snapshot_id": self.dataset_snapshot_id,
            "dataset_content_hash": self.dataset_content_hash,
            "stream_hash": self.stream_hash,
            "event_count": self.event_count,
            "event_counts_by_type": counts,
            "pre_known_event_count": self.pre_known_event_count,
            "boundary_ok": self.boundary_ok,
            "warning_count": self.warning_count,
            "error_count": self.error_count,
            "first_event_time": _iso(self.first_event_time),
            "last_event_time": _iso(self.last_event_time),
            "first_market_event_time": _iso(self.first_market_event_time),
            "last_market_event_time": _iso(self.last_market_event_time),
            "request": dict(self.request),
            "audit_summary": dict(self.audit_summary),
            "artifacts": [item.as_mapping() for item in self.artifacts],
            "notes": self.notes,
        }
        if include_manifest_hash:
            payload["manifest_hash"] = self.manifest_hash
        return payload


@dataclass(frozen=True, slots=True)
class ReplayRunResult:
    manifest: ReplayRunManifest
    output_dir: Path
    events_path: Path
    audit_path: Path
    summary_path: Path
    manifest_path: Path


@dataclass(frozen=True, slots=True)
class ReplayRunCatalogEntry:
    replay_id: str
    stream_hash: str
    manifest_hash: str
    source_type: str
    dataset_snapshot_id: str | None
    dataset_content_hash: str | None
    package_version: str
    git_commit: str | None
    created_at: datetime
    as_of: datetime | None
    start_time: datetime | None
    end_time: datetime | None
    event_count: int
    market_event_count: int
    session_event_count: int
    corporate_action_event_count: int
    pre_known_event_count: int
    warning_count: int
    error_count: int
    boundary_ok: bool
    is_reproducible: bool
    is_usable: bool
    request: dict[str, object]
    audit_summary: dict[str, object]
    artifacts: tuple[dict[str, object], ...]
    notes: str | None
    registered_at: datetime

    def as_mapping(self) -> dict[str, object]:
        return {
            "replay_id": self.replay_id,
            "stream_hash": self.stream_hash,
            "manifest_hash": self.manifest_hash,
            "source_type": self.source_type,
            "dataset_snapshot_id": self.dataset_snapshot_id,
            "dataset_content_hash": self.dataset_content_hash,
            "package_version": self.package_version,
            "git_commit": self.git_commit,
            "created_at": self.created_at.isoformat(),
            "as_of": None if self.as_of is None else self.as_of.isoformat(),
            "start_time": (
                None if self.start_time is None else self.start_time.isoformat()
            ),
            "end_time": None if self.end_time is None else self.end_time.isoformat(),
            "event_count": self.event_count,
            "market_event_count": self.market_event_count,
            "session_event_count": self.session_event_count,
            "corporate_action_event_count": self.corporate_action_event_count,
            "pre_known_event_count": self.pre_known_event_count,
            "warning_count": self.warning_count,
            "error_count": self.error_count,
            "boundary_ok": self.boundary_ok,
            "is_reproducible": self.is_reproducible,
            "is_usable": self.is_usable,
            "request": dict(self.request),
            "audit_summary": dict(self.audit_summary),
            "artifacts": [dict(item) for item in self.artifacts],
            "notes": self.notes,
            "registered_at": self.registered_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class ReplayRunComparison:
    replay_a_id: str
    replay_b_id: str
    same_stream_hash: bool
    same_manifest_hash: bool
    same_source_type: bool
    same_boundary_ok: bool
    same_package_version: bool
    same_git_commit: bool
    same_dataset_snapshot_id: bool
    same_dataset_content_hash: bool
    same_artifact_paths: bool
    event_count_delta: int
    error_count_delta: int
    warning_count_delta: int
    pre_known_event_count_delta: int
    differences: tuple[str, ...]

    def as_mapping(self) -> dict[str, object]:
        return {
            "replay_a_id": self.replay_a_id,
            "replay_b_id": self.replay_b_id,
            "same_stream_hash": self.same_stream_hash,
            "same_manifest_hash": self.same_manifest_hash,
            "same_source_type": self.same_source_type,
            "same_boundary_ok": self.same_boundary_ok,
            "same_package_version": self.same_package_version,
            "same_git_commit": self.same_git_commit,
            "same_dataset_snapshot_id": self.same_dataset_snapshot_id,
            "same_dataset_content_hash": self.same_dataset_content_hash,
            "same_artifact_paths": self.same_artifact_paths,
            "event_count_delta": self.event_count_delta,
            "error_count_delta": self.error_count_delta,
            "warning_count_delta": self.warning_count_delta,
            "pre_known_event_count_delta": self.pre_known_event_count_delta,
            "differences": list(self.differences),
        }


@dataclass(frozen=True, slots=True)
class ReplayRunRegistration:
    entry: ReplayRunCatalogEntry
    action: str


@dataclass(frozen=True, slots=True)
class ReplayRunCatalogFilters:
    stream_hash: str | None = None
    usable_only: bool = False
    boundary_ok: bool | None = None
    source_type: str | None = None
    dataset_snapshot_id: str | None = None


def build_replay_run_catalog_filters(
    *,
    stream_hash: str | None = None,
    usable_only: bool = False,
    boundary_ok: bool | None = None,
    source_type: str | None = None,
    dataset_snapshot_id: str | None = None,
) -> ReplayRunCatalogFilters:
    cleaned_source = _optional_token(source_type, field="source_type")
    if cleaned_source is not None and cleaned_source not in SOURCE_TYPES:
        raise SimulationError(
            "source_type must be 'database' or 'snapshot'",
            code=SimulationErrorCode.CATALOG_INVALID,
        )
    return ReplayRunCatalogFilters(
        stream_hash=_optional_token(stream_hash, field="stream_hash"),
        usable_only=usable_only,
        boundary_ok=boundary_ok,
        source_type=cleaned_source,
        dataset_snapshot_id=_optional_token(
            dataset_snapshot_id, field="dataset_snapshot_id"
        ),
    )


def _optional_token(value: str | None, *, field: str) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        raise SimulationError(
            f"{field} must not be empty",
            code=SimulationErrorCode.CATALOG_INVALID,
        )
    return stripped
