"""Typed snapshot artifact integrity reports. Dataclasses, not Pydantic."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class IntegritySeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class IntegrityIssueCode(StrEnum):
    MISSING_MANIFEST = "missing_manifest"
    MISSING_ARTIFACT = "missing_artifact"
    MISSING_SNAPSHOT_DIR = "missing_snapshot_dir"
    ABSOLUTE_PATH = "absolute_path"
    PATH_ESCAPE = "path_escape"
    INVALID_HASH = "invalid_hash"
    MANIFEST_HASH_MISMATCH = "manifest_hash_mismatch"
    CONTENT_HASH_MISMATCH = "content_hash_mismatch"
    QUALITY_HASH_MISMATCH = "quality_hash_mismatch"
    SECRET_LIKE_VALUE = "secret_like_value"  # noqa: S105
    ROW_COUNT_MISMATCH = "row_count_mismatch"
    INSTRUMENT_COUNT_MISMATCH = "instrument_count_mismatch"
    CATALOG_MANIFEST_MISMATCH = "catalog_manifest_mismatch"
    CATALOG_ENTRY_MISSING = "catalog_entry_missing"
    INVALID_JSON = "invalid_json"
    INVALID_CSV = "invalid_csv"
    EMPTY_ARTIFACT_PATH = "empty_artifact_path"


SEVERITY_RANK: dict[str, int] = {
    IntegritySeverity.ERROR.value: 0,
    IntegritySeverity.WARNING.value: 1,
    IntegritySeverity.INFO.value: 2,
}


@dataclass(frozen=True, slots=True)
class ArtifactVerificationRequest:
    snapshot_root: Path
    expected_snapshot_id: str | None = None


@dataclass(frozen=True, slots=True)
class ArtifactVerificationIssue:
    severity: str
    code: str
    message: str
    path: str | None = None
    expected: str | None = None
    actual: str | None = None

    def as_mapping(self) -> dict[str, object]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "path": self.path,
            "expected": self.expected,
            "actual": self.actual,
        }


@dataclass(frozen=True, slots=True)
class SnapshotArtifactStatus:
    name: str
    path: str
    exists: bool
    relative: bool
    escaped: bool

    def as_mapping(self) -> dict[str, object]:
        return {
            "name": self.name,
            "path": self.path,
            "exists": self.exists,
            "relative": self.relative,
            "escaped": self.escaped,
        }


@dataclass(frozen=True, slots=True)
class ArtifactVerificationReport:
    snapshot_root: str
    snapshot_id: str | None
    ok: bool
    error_count: int
    warning_count: int
    info_count: int
    issues: tuple[ArtifactVerificationIssue, ...]
    artifacts: tuple[SnapshotArtifactStatus, ...]
    content_hash: str | None
    recomputed_content_hash: str | None
    quality_hash: str | None
    recomputed_quality_hash: str | None
    manifest_hash: str | None
    recomputed_manifest_hash: str | None
    row_count: int | None
    csv_row_count: int | None
    instrument_count: int | None
    csv_instrument_count: int | None

    def as_mapping(self) -> dict[str, object]:
        return {
            "snapshot_root": self.snapshot_root,
            "snapshot_id": self.snapshot_id,
            "ok": self.ok,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "info_count": self.info_count,
            "issues": [item.as_mapping() for item in self.issues],
            "artifacts": [item.as_mapping() for item in self.artifacts],
            "content_hash": self.content_hash,
            "recomputed_content_hash": self.recomputed_content_hash,
            "quality_hash": self.quality_hash,
            "recomputed_quality_hash": self.recomputed_quality_hash,
            "manifest_hash": self.manifest_hash,
            "recomputed_manifest_hash": self.recomputed_manifest_hash,
            "row_count": self.row_count,
            "csv_row_count": self.csv_row_count,
            "instrument_count": self.instrument_count,
            "csv_instrument_count": self.csv_instrument_count,
        }


@dataclass(frozen=True, slots=True)
class CatalogIntegrityReport:
    base_dir: str
    entry_count: int
    verified_count: int
    error_count: int
    warning_count: int
    ok: bool
    reports: tuple[ArtifactVerificationReport, ...]

    def as_mapping(self) -> dict[str, object]:
        return {
            "base_dir": self.base_dir,
            "entry_count": self.entry_count,
            "verified_count": self.verified_count,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "ok": self.ok,
            "reports": [item.as_mapping() for item in self.reports],
        }
