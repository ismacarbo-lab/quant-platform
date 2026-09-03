"""Normalized-dataset catalog shapes. Metadata only; not bar storage."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from quant_platform.research.normalization.errors import (
    NormalizationError,
    NormalizationErrorCode,
)
from quant_platform.research.normalization.types import parse_adjustment_mode

SOURCE_LOCAL_ARTIFACTS = "local_artifacts"
SOURCE_SNAPSHOT = "snapshot"
SOURCE_REPLAY = "replay"
SOURCE_RESEARCH_DATASET = "research_dataset"
ALLOWED_SOURCE_TYPES = frozenset(
    {
        SOURCE_LOCAL_ARTIFACTS,
        SOURCE_SNAPSHOT,
        SOURCE_REPLAY,
        SOURCE_RESEARCH_DATASET,
    }
)

COMPARISON_IDENTICAL = "identical"
COMPARISON_SAME_DATASET = "same_dataset"
COMPARISON_DIFFERENT = "different"


class NormalizedDatasetUsabilitySeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class NormalizedDatasetUsabilityCode(StrEnum):
    MISSING_CATALOG_ROW = "missing_catalog_row"
    MISSING_ARTIFACT = "missing_artifact"
    INVALID_HASH = "invalid_hash"
    HASH_MISMATCH = "hash_mismatch"
    ABSOLUTE_PATH = "absolute_path"
    SECRET_LIKE_VALUE = "secret_like_value"  # noqa: S105
    FORBIDDEN_METRIC = "forbidden_metric"
    OPERATIVE_LANGUAGE = "operative_language"
    INTEGRITY_FAILED = "integrity_failed"
    CATALOG_ERRORS = "catalog_errors"


@dataclass(frozen=True, slots=True)
class NormalizedDatasetCatalogFilters:
    dataset_hash: str | None = None
    raw_dataset_hash: str | None = None
    adjustment_mode: str | None = None
    usable_only: bool = False
    source_snapshot_id: str | None = None
    source_replay_id: str | None = None


def build_normalized_dataset_catalog_filters(
    *,
    dataset_hash: str | None = None,
    raw_dataset_hash: str | None = None,
    adjustment_mode: str | None = None,
    usable_only: bool = False,
    source_snapshot_id: str | None = None,
    source_replay_id: str | None = None,
) -> NormalizedDatasetCatalogFilters:
    """Validate list filters. Does not query PostgreSQL."""
    mode = _optional_token(adjustment_mode, field="adjustment_mode")
    if mode is not None:
        parse_adjustment_mode(mode)
    return NormalizedDatasetCatalogFilters(
        dataset_hash=_optional_token(dataset_hash, field="dataset_hash"),
        raw_dataset_hash=_optional_token(raw_dataset_hash, field="raw_dataset_hash"),
        adjustment_mode=mode,
        usable_only=usable_only,
        source_snapshot_id=_optional_token(
            source_snapshot_id, field="source_snapshot_id"
        ),
        source_replay_id=_optional_token(source_replay_id, field="source_replay_id"),
    )


def _optional_token(value: str | None, *, field: str) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        raise NormalizationError(
            f"{field} must not be empty",
            code=NormalizationErrorCode.EMPTY_FILTER,
        )
    return stripped


@dataclass(frozen=True, slots=True)
class NormalizedDatasetCatalogEntry:
    normalized_dataset_id: str
    dataset_hash: str
    raw_dataset_hash: str | None
    source_type: str
    source_snapshot_id: str | None
    source_replay_id: str | None
    adjustment_mode: str
    as_of: datetime
    start_time: datetime
    end_time: datetime
    symbol_count: int
    bar_count: int
    adjusted_bar_count: int
    applied_action_count: int
    warning_count: int
    error_count: int
    is_reproducible: bool
    is_usable: bool
    artifacts: tuple[dict[str, object], ...]
    request: dict[str, object]
    report_summary: dict[str, object]
    manifest_hash: str
    package_version: str
    git_commit: str | None
    created_at: datetime
    registered_at: datetime
    notes: str | None = None

    def as_mapping(self) -> dict[str, object]:
        return {
            "normalized_dataset_id": self.normalized_dataset_id,
            "dataset_hash": self.dataset_hash,
            "raw_dataset_hash": self.raw_dataset_hash,
            "source_type": self.source_type,
            "source_snapshot_id": self.source_snapshot_id,
            "source_replay_id": self.source_replay_id,
            "adjustment_mode": self.adjustment_mode,
            "as_of": self.as_of.isoformat(),
            "start": self.start_time.isoformat(),
            "end": self.end_time.isoformat(),
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "symbol_count": self.symbol_count,
            "bar_count": self.bar_count,
            "adjusted_bar_count": self.adjusted_bar_count,
            "applied_action_count": self.applied_action_count,
            "warning_count": self.warning_count,
            "error_count": self.error_count,
            "is_reproducible": self.is_reproducible,
            "is_usable": self.is_usable,
            "artifacts": list(self.artifacts),
            "request": dict(self.request),
            "report_summary": dict(self.report_summary),
            "manifest_hash": self.manifest_hash,
            "package_version": self.package_version,
            "git_commit": self.git_commit,
            "created_at": self.created_at.isoformat(),
            "registered_at": self.registered_at.isoformat(),
            "notes": self.notes,
        }


@dataclass(frozen=True, slots=True)
class NormalizedDatasetRegistration:
    entry: NormalizedDatasetCatalogEntry
    action: str = ""

    def as_mapping(self) -> dict[str, object]:
        payload = self.entry.as_mapping()
        payload["action"] = self.action
        return payload


@dataclass(frozen=True, slots=True)
class NormalizedDatasetComparison:
    left_id: str
    right_id: str
    verdict: str
    same_dataset_hash: bool
    same_raw_dataset_hash: bool
    same_adjustment_mode: bool
    same_as_of: bool
    same_bar_count: bool
    same_adjusted_bar_count: bool
    same_applied_action_count: bool
    same_warning_count: bool
    same_error_count: bool
    same_artifacts: bool
    same_manifest_hash: bool
    differences: tuple[str, ...]

    def as_mapping(self) -> dict[str, object]:
        return {
            "left_id": self.left_id,
            "right_id": self.right_id,
            "verdict": self.verdict,
            "same_dataset_hash": self.same_dataset_hash,
            "same_raw_dataset_hash": self.same_raw_dataset_hash,
            "same_adjustment_mode": self.same_adjustment_mode,
            "same_as_of": self.same_as_of,
            "same_bar_count": self.same_bar_count,
            "same_adjusted_bar_count": self.same_adjusted_bar_count,
            "same_applied_action_count": self.same_applied_action_count,
            "same_warning_count": self.same_warning_count,
            "same_error_count": self.same_error_count,
            "same_artifacts": self.same_artifacts,
            "same_manifest_hash": self.same_manifest_hash,
            "differences": list(self.differences),
        }


@dataclass(frozen=True, slots=True)
class NormalizedDatasetUsabilityIssue:
    severity: str
    code: str
    message: str

    def as_mapping(self) -> dict[str, object]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class NormalizedDatasetUsabilityReport:
    ok: bool
    usable: bool
    reproducible: bool
    normalized_dataset_id: str
    dataset_hash: str | None
    raw_dataset_hash: str | None
    run_root: str | None
    error_count: int
    warning_count: int
    issues: tuple[NormalizedDatasetUsabilityIssue, ...]

    def as_mapping(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "usable": self.usable,
            "reproducible": self.reproducible,
            "normalized_dataset_id": self.normalized_dataset_id,
            "dataset_hash": self.dataset_hash,
            "raw_dataset_hash": self.raw_dataset_hash,
            "run_root": self.run_root,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "issues": [item.as_mapping() for item in self.issues],
        }


def artifacts_have_absolute_paths(artifacts: Sequence[Mapping[str, object]]) -> bool:
    return any(_artifact_path_is_absolute(item) for item in artifacts)


def _artifact_path_is_absolute(item: Mapping[str, object]) -> bool:
    path = item.get("path")
    if not isinstance(path, str) or not path.strip():
        return True
    candidate = Path(path)
    return candidate.is_absolute() or ".." in candidate.parts
