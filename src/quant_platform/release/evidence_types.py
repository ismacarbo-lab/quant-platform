"""Typed research evidence-bundle shapes. Not a trading or PnL report."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from quant_platform.backtest.types import DATA_QUALITY_POLICY_NAME
from quant_platform.research.snapshots import canonical_datetime
from quant_platform.simulation.run_types import artifact_path_is_unsafe

EVIDENCE_BUNDLE_KIND = "research_evidence_bundle"
EVIDENCE_BUNDLE_FORMAT_VERSION = 1
EVIDENCE_HASH_KIND = "research_evidence_bundle"
EVIDENCE_HASH_FORMAT_VERSION = 1

EVIDENCE_MANIFEST_NAME = "evidence_manifest.json"
EVIDENCE_SUMMARY_NAME = "evidence_summary.json"
RELEASE_STATUS_NAME = "release_status.json"

SNAPSHOT_DIRNAME = "dataset_snapshot"
REPLAY_DIRNAME = "replay_run"
BACKTEST_DIRNAME = "backtest_run"
EXPERIMENT_DIRNAME = "experiment"
REPORTS_DIRNAME = "reports"

DEFAULT_POLICY_NAME = DATA_QUALITY_POLICY_NAME
DEFAULT_EXPERIMENT_NAME = "e2e-research-evidence"

STEP_VALIDATE_MODE = "validate_research_mode"
STEP_VALIDATE_ALEMBIC = "validate_alembic_head"
STEP_VALIDATE_POLICY = "validate_policy"
STEP_LOAD_FIXTURES = "load_fixtures"
STEP_INGEST = "ingest_daily_bars"
STEP_CORRECTIONS = "apply_corrections"
STEP_QUALITY = "dataset_quality"
STEP_SNAPSHOT = "dataset_snapshot"
STEP_CATALOG = "catalog_snapshot"
STEP_REPLAY = "replay_run"
STEP_READINESS = "replay_readiness"
STEP_BACKTEST = "backtest_dry_run"
STEP_BACKTEST_USABILITY = "backtest_usability"
STEP_EXPERIMENT = "experiment"
STEP_EXPERIMENT_USABILITY = "experiment_usability"
STEP_RESEARCH_REPORT = "research_report"
STEP_RELEASE_STATUS = "release_status"
STEP_WRITE_MANIFEST = "write_manifest"
STEP_NORMALIZATION = "normalization"
NORMALIZED_DATASET_DIRNAME = "normalized_dataset"
DEFAULT_NORMALIZATION_ADJUSTMENT_MODE = "split_only"

EVIDENCE_STEPS: tuple[str, ...] = (
    STEP_VALIDATE_MODE,
    STEP_VALIDATE_ALEMBIC,
    STEP_VALIDATE_POLICY,
    STEP_LOAD_FIXTURES,
    STEP_INGEST,
    STEP_CORRECTIONS,
    STEP_QUALITY,
    STEP_SNAPSHOT,
    STEP_CATALOG,
    STEP_REPLAY,
    STEP_READINESS,
    STEP_BACKTEST,
    STEP_BACKTEST_USABILITY,
    STEP_EXPERIMENT,
    STEP_EXPERIMENT_USABILITY,
    STEP_RESEARCH_REPORT,
    STEP_RELEASE_STATUS,
    STEP_WRITE_MANIFEST,
)

STEP_STATUS_OK = "ok"
STEP_STATUS_ERROR = "error"
STEP_STATUS_SKIPPED = "skipped"


class EvidenceBundleError(Exception):
    """Evidence-bundle coordination failed. Not a trading error."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def _relative_path(path: str) -> str:
    cleaned = path.strip().replace("\\", "/")
    if artifact_path_is_unsafe(cleaned):
        raise EvidenceBundleError(
            "evidence artifact paths must be relative",
            code="absolute_path",
        )
    return cleaned


@dataclass(frozen=True, slots=True)
class ResearchEvidenceBundleRequest:
    fixture_dir: Path
    output_dir: Path
    policy_name: str = DEFAULT_POLICY_NAME
    policy_config: dict[str, object] | None = None
    deterministic_id: bool = False
    created_at: datetime | None = None
    git_commit: str | None = None
    resolve_git: bool = True
    source_name: str | None = None
    notes: str | None = None
    research_mode: bool | None = None
    skip_compose: bool = True
    skip_regression: bool = True
    skip_release_db: bool = True
    skip_normalization_regression: bool = True
    include_normalized_dataset: bool = False
    normalization_adjustment_mode: str = DEFAULT_NORMALIZATION_ADJUSTMENT_MODE

    def __post_init__(self) -> None:
        object.__setattr__(self, "fixture_dir", Path(self.fixture_dir))
        object.__setattr__(self, "output_dir", Path(self.output_dir))
        object.__setattr__(self, "policy_name", self.policy_name.strip())
        if self.source_name is not None:
            cleaned = self.source_name.strip()
            object.__setattr__(self, "source_name", cleaned or None)
        if self.notes is not None:
            stripped = self.notes.strip()
            object.__setattr__(self, "notes", stripped or None)
        if self.policy_config is not None:
            object.__setattr__(self, "policy_config", dict(self.policy_config))
        object.__setattr__(
            self,
            "normalization_adjustment_mode",
            self.normalization_adjustment_mode.strip()
            or DEFAULT_NORMALIZATION_ADJUSTMENT_MODE,
        )


@dataclass(frozen=True, slots=True)
class ResearchEvidenceBundleStep:
    name: str
    status: str
    detail: str | None = None

    def as_mapping(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class ResearchEvidenceBundleArtifact:
    name: str
    path: str
    kind: str

    def as_mapping(self) -> dict[str, object]:
        return {
            "name": self.name,
            "path": _relative_path(self.path),
            "kind": self.kind,
        }


@dataclass(frozen=True, slots=True)
class ResearchEvidenceBundleIssue:
    severity: str
    code: str
    message: str
    step: str | None = None

    def as_mapping(self) -> dict[str, object]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "step": self.step,
        }


@dataclass(frozen=True, slots=True)
class ResearchEvidenceBundleManifest:
    bundle_id: str
    created_at: datetime
    package_version: str
    git_commit: str | None
    app_mode: str
    alembic_head: str | None
    dataset_snapshot_id: str | None
    replay_id: str | None
    backtest_id: str | None
    experiment_id: str | None
    snapshot_hash: str | None
    stream_hash: str | None
    backtest_hash: str | None
    experiment_hash: str | None
    report_hash: str | None
    release_report_hash: str | None
    steps: tuple[ResearchEvidenceBundleStep, ...]
    artifacts: tuple[ResearchEvidenceBundleArtifact, ...]
    warnings: tuple[ResearchEvidenceBundleIssue, ...]
    errors: tuple[ResearchEvidenceBundleIssue, ...]
    ok: bool
    bundle_hash: str
    replay_ready: bool | None = None
    backtest_usable: bool | None = None
    experiment_usable: bool | None = None
    release_ok: bool | None = None
    policy_name: str = DEFAULT_POLICY_NAME
    normalized_dataset_hash: str | None = None

    def as_mapping(self, *, include_bundle_hash: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "kind": EVIDENCE_BUNDLE_KIND,
            "format_version": EVIDENCE_BUNDLE_FORMAT_VERSION,
            "bundle_id": self.bundle_id,
            "created_at": canonical_datetime(self.created_at),
            "package_version": self.package_version,
            "git_commit": self.git_commit,
            "app_mode": self.app_mode,
            "alembic_head": self.alembic_head,
            "policy_name": self.policy_name,
            "dataset_snapshot_id": self.dataset_snapshot_id,
            "replay_id": self.replay_id,
            "backtest_id": self.backtest_id,
            "experiment_id": self.experiment_id,
            "snapshot_hash": self.snapshot_hash,
            "stream_hash": self.stream_hash,
            "backtest_hash": self.backtest_hash,
            "experiment_hash": self.experiment_hash,
            "report_hash": self.report_hash,
            "release_report_hash": self.release_report_hash,
            "replay_ready": self.replay_ready,
            "backtest_usable": self.backtest_usable,
            "experiment_usable": self.experiment_usable,
            "release_ok": self.release_ok,
            "ok": self.ok,
            "step_count": len(self.steps),
            "artifact_count": len(self.artifacts),
            "warning_count": len(self.warnings),
            "error_count": len(self.errors),
            "steps": [item.as_mapping() for item in self.steps],
            "artifacts": [item.as_mapping() for item in self.artifacts],
            "warnings": [item.as_mapping() for item in self.warnings],
            "errors": [item.as_mapping() for item in self.errors],
        }
        if self.normalized_dataset_hash is not None:
            payload["normalized_dataset_hash"] = self.normalized_dataset_hash
        if include_bundle_hash:
            payload["bundle_hash"] = self.bundle_hash
        return payload


@dataclass(frozen=True, slots=True)
class ResearchEvidenceBundleResult:
    request: ResearchEvidenceBundleRequest
    manifest: ResearchEvidenceBundleManifest
    output_dir: Path
    release_status: dict[str, object] | None = None

    @property
    def ok(self) -> bool:
        return self.manifest.ok

    @property
    def bundle_hash(self) -> str:
        return self.manifest.bundle_hash

    def as_mapping(self) -> dict[str, object]:
        return self.manifest.as_mapping()

    def summary_mapping(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "kind": EVIDENCE_BUNDLE_KIND,
            "format_version": EVIDENCE_BUNDLE_FORMAT_VERSION,
            "bundle_id": self.manifest.bundle_id,
            "created_at": canonical_datetime(self.manifest.created_at),
            "package_version": self.manifest.package_version,
            "git_commit": self.manifest.git_commit,
            "app_mode": self.manifest.app_mode,
            "alembic_head": self.manifest.alembic_head,
            "policy_name": self.manifest.policy_name,
            "dataset_snapshot_id": self.manifest.dataset_snapshot_id,
            "replay_id": self.manifest.replay_id,
            "backtest_id": self.manifest.backtest_id,
            "experiment_id": self.manifest.experiment_id,
            "snapshot_hash": self.manifest.snapshot_hash,
            "stream_hash": self.manifest.stream_hash,
            "backtest_hash": self.manifest.backtest_hash,
            "experiment_hash": self.manifest.experiment_hash,
            "report_hash": self.manifest.report_hash,
            "release_report_hash": self.manifest.release_report_hash,
            "replay_ready": self.manifest.replay_ready,
            "backtest_usable": self.manifest.backtest_usable,
            "experiment_usable": self.manifest.experiment_usable,
            "release_ok": self.manifest.release_ok,
            "ok": self.manifest.ok,
            "bundle_hash": self.manifest.bundle_hash,
            "step_count": len(self.manifest.steps),
            "artifact_count": len(self.manifest.artifacts),
            "warning_count": len(self.manifest.warnings),
            "error_count": len(self.manifest.errors),
            "steps": [item.as_mapping() for item in self.manifest.steps],
        }
        if self.manifest.normalized_dataset_hash is not None:
            payload["normalized_dataset_hash"] = self.manifest.normalized_dataset_hash
        return payload


def default_evidence_artifacts() -> tuple[ResearchEvidenceBundleArtifact, ...]:
    return (
        ResearchEvidenceBundleArtifact(
            name="manifest", path=EVIDENCE_MANIFEST_NAME, kind="json"
        ),
        ResearchEvidenceBundleArtifact(
            name="summary", path=EVIDENCE_SUMMARY_NAME, kind="json"
        ),
        ResearchEvidenceBundleArtifact(
            name="release_status", path=RELEASE_STATUS_NAME, kind="json"
        ),
    )
