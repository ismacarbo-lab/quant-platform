"""Build a local research evidence bundle from existing APIs. Not trading."""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from quant_platform import __version__
from quant_platform.backtest.catalog import register_backtest_run
from quant_platform.backtest.engine import run_backtest_from_replay_run
from quant_platform.backtest.errors import BacktestError
from quant_platform.backtest.experiment_catalog import get_backtest_experiment_by_id
from quant_platform.backtest.experiment_readiness import (
    evaluate_backtest_experiment_usability,
)
from quant_platform.backtest.experiment_report_artifacts import (
    write_backtest_experiment_report_artifacts,
)
from quant_platform.backtest.experiment_reports import (
    build_research_report_from_catalog,
    load_member_observation_reports,
)
from quant_platform.backtest.experiment_types import (
    EXPERIMENT_MANIFEST_ARTIFACT_NAME,
    EXPERIMENT_RESEARCH_REPORT_ARTIFACT_NAME,
    EXPERIMENT_SUMMARY_ARTIFACT_NAME,
    EXPERIMENT_USABILITY_ARTIFACT_NAME,
    BacktestExperimentRequest,
)
from quant_platform.backtest.experiments import (
    members_from_experiment_summary,
    run_backtest_experiment,
)
from quant_platform.backtest.policy_registry import (
    get_research_policy,
    is_registered_policy,
)
from quant_platform.backtest.readiness import evaluate_backtest_result_usability
from quant_platform.backtest.types import (
    MANIFEST_ARTIFACT_NAME as BACKTEST_MANIFEST_NAME,
)
from quant_platform.backtest.types import (
    POLICY_OUTPUT_ARTIFACT_NAME,
    BacktestRequest,
)
from quant_platform.backtest.types import (
    SUMMARY_ARTIFACT_NAME as BACKTEST_SUMMARY_NAME,
)
from quant_platform.core.config import get_settings
from quant_platform.core.redact import redact_secret_text
from quant_platform.core.time import utc_now
from quant_platform.data.csv_loader import (
    CsvLoadError,
    ErrorMode,
    parse_observation_time,
    parse_utc_datetime,
)
from quant_platform.data.ingest import IngestResult, ingest_daily_bars_csv
from quant_platform.data.models import DataSource, IngestionRun, IngestionStatus
from quant_platform.data.reference_csv import (
    load_calendars_csv,
    load_corporate_actions_csv,
    load_exchanges_csv,
    load_sessions_csv,
)
from quant_platform.data.repository import (
    create_ingestion_run,
    finish_ingestion_run,
    get_daily_bars,
    get_market_calendar_by_code,
    insert_daily_bar_correction,
    upsert_data_source,
    upsert_instrument,
)
from quant_platform.data.validation import DataValidationError, parse_decimal
from quant_platform.release.checks import run_research_release_checks
from quant_platform.release.constants import EXPECTED_ALEMBIC_HEAD
from quant_platform.release.evidence_artifacts import (
    without_local_paths,
    write_evidence_json,
    write_research_evidence_artifacts,
)
from quant_platform.release.evidence_fixture_reuse import (
    check_existing_evidence_fixture_data,
    existing_fixture_daily_bars_present,
    fixture_csv_row_count,
)
from quant_platform.release.evidence_types import (
    BACKTEST_DIRNAME,
    DEFAULT_EXPERIMENT_NAME,
    EVIDENCE_HASH_FORMAT_VERSION,
    EVIDENCE_HASH_KIND,
    EVIDENCE_STEPS,
    EXPERIMENT_DIRNAME,
    NORMALIZED_DATASET_DIRNAME,
    RELEASE_STATUS_NAME,
    REPLAY_DIRNAME,
    REPORTS_DIRNAME,
    SNAPSHOT_DIRNAME,
    STEP_BACKTEST,
    STEP_BACKTEST_USABILITY,
    STEP_CATALOG,
    STEP_CORRECTIONS,
    STEP_EXPERIMENT,
    STEP_EXPERIMENT_USABILITY,
    STEP_FIXTURE_DATA,
    STEP_INGEST,
    STEP_LOAD_FIXTURES,
    STEP_NORMALIZATION,
    STEP_QUALITY,
    STEP_READINESS,
    STEP_RELEASE_STATUS,
    STEP_REPLAY,
    STEP_RESEARCH_REPORT,
    STEP_SNAPSHOT,
    STEP_STATUS_ERROR,
    STEP_STATUS_OK,
    STEP_STATUS_SKIPPED,
    STEP_VALIDATE_ALEMBIC,
    STEP_VALIDATE_MODE,
    STEP_VALIDATE_POLICY,
    STEP_WRITE_MANIFEST,
    EvidenceBundleError,
    EvidenceFixtureDataMode,
    EvidenceFixtureReuseReport,
    ResearchEvidenceBundleArtifact,
    ResearchEvidenceBundleIssue,
    ResearchEvidenceBundleManifest,
    ResearchEvidenceBundleRequest,
    ResearchEvidenceBundleResult,
    ResearchEvidenceBundleStep,
    default_evidence_artifacts,
    empty_fixture_reuse_report,
)
from quant_platform.release.status import (
    alembic_script_heads,
    hash_release_status_report,
)
from quant_platform.research.catalog import register_dataset_snapshot
from quant_platform.research.errors import DatasetValidationError
from quant_platform.research.normalization.artifacts import (
    write_normalized_dataset_artifacts,
)
from quant_platform.research.normalization.catalog import (
    build_normalized_dataset_registration,
    evaluate_normalized_dataset_usability,
    register_normalized_dataset,
)
from quant_platform.research.normalization.datasets import (
    build_normalized_daily_bars_dataset,
)
from quant_platform.research.normalization.errors import NormalizationError
from quant_platform.research.normalization.integrity import (
    verify_normalization_artifacts,
)
from quant_platform.research.normalization.types import (
    BARS_ARTIFACT_NAME as NORMALIZED_BARS_ARTIFACT_NAME,
)
from quant_platform.research.normalization.types import (
    MANIFEST_ARTIFACT_NAME as NORMALIZATION_MANIFEST_NAME,
)
from quant_platform.research.normalization.types import (
    REPORT_ARTIFACT_NAME as NORMALIZATION_REPORT_NAME,
)
from quant_platform.research.normalization.types import build_normalization_request
from quant_platform.research.quality import (
    get_dataset_quality_report,
    write_dataset_quality_json,
)
from quant_platform.research.quality_types import build_dataset_quality_request
from quant_platform.research.snapshot_types import (
    DAILY_BARS_ARTIFACT_NAME,
    MANIFEST_ARTIFACT_NAME,
    QUALITY_ARTIFACT_NAME,
    build_dataset_snapshot_request,
)
from quant_platform.research.snapshots import (
    canonical_json,
    create_daily_bars_snapshot,
    get_git_commit,
    hash_quality_report,
    manifest_contains_secrets,
    sha256_canonical,
)
from quant_platform.simulation.artifacts import write_replay_run_artifacts
from quant_platform.simulation.audit import audit_replay
from quant_platform.simulation.errors import SimulationError
from quant_platform.simulation.readiness import evaluate_replay_run_readiness
from quant_platform.simulation.replay import create_daily_bar_replay
from quant_platform.simulation.run_catalog import register_replay_run
from quant_platform.simulation.run_types import (
    AUDIT_ARTIFACT_NAME,
    EVENTS_ARTIFACT_NAME,
    SUMMARY_ARTIFACT_NAME,
)

_REQUIRED_FIXTURES = (
    "daily_bars.csv",
    "exchanges.csv",
    "calendars.csv",
    "sessions.csv",
    "corporate_actions.csv",
)


@dataclass(frozen=True, slots=True)
class _FixtureSpec:
    as_of: datetime
    start_time: datetime
    end_time: datetime
    symbols: tuple[str, ...]
    exchange_codes: tuple[str, ...]
    calendar_code: str
    asset_class: str
    currency: str
    source_name: str
    vendor: str


class _StepFailed(Exception):
    def __init__(self, name: str, code: str, message: str) -> None:
        super().__init__(message)
        self.name = name
        self.code = code
        self.message = message


def hash_research_evidence_bundle(
    manifest_or_summary: (
        ResearchEvidenceBundleManifest
        | ResearchEvidenceBundleResult
        | Mapping[str, object]
    ),
) -> str:
    """SHA-256 of evidence hashes and step statuses. No wall-clock or ids."""
    payload = _hash_source_mapping(manifest_or_summary)
    steps = payload.get("steps")
    step_rows: list[dict[str, object]] = []
    if isinstance(steps, list):
        for item in steps:
            if isinstance(item, Mapping):
                step_rows.append(
                    {
                        "name": str(item.get("name") or ""),
                        "status": str(item.get("status") or ""),
                    }
                )
    digest = {
        "kind": EVIDENCE_HASH_KIND,
        "version": EVIDENCE_HASH_FORMAT_VERSION,
        "package_version": payload.get("package_version"),
        "app_mode": payload.get("app_mode"),
        "alembic_head": payload.get("alembic_head"),
        "snapshot_hash": payload.get("snapshot_hash"),
        "stream_hash": payload.get("stream_hash"),
        "backtest_hash": payload.get("backtest_hash"),
        "experiment_hash": payload.get("experiment_hash"),
        "report_hash": payload.get("report_hash"),
        "release_report_hash": payload.get("release_report_hash"),
        "ok": payload.get("ok"),
        "error_count": payload.get("error_count"),
        "steps": step_rows,
    }
    normalized_hash = payload.get("normalized_dataset_hash")
    if normalized_hash:
        digest["normalized_dataset_hash"] = normalized_hash
    fixture_mode = payload.get("fixture_data_mode")
    if fixture_mode:
        digest["fixture_data_mode"] = fixture_mode
    reuse = payload.get("fixture_reuse")
    if isinstance(reuse, Mapping):
        digest["fixture_reuse"] = {
            "inserted_bar_count": reuse.get("inserted_bar_count"),
            "reused_bar_count": reuse.get("reused_bar_count"),
            "inserted_corporate_action_count": reuse.get(
                "inserted_corporate_action_count"
            ),
            "reused_corporate_action_count": reuse.get("reused_corporate_action_count"),
            "inserted_session_count": reuse.get("inserted_session_count"),
            "reused_session_count": reuse.get("reused_session_count"),
        }
    blob = canonical_json(digest)
    if manifest_contains_secrets(blob):
        raise EvidenceBundleError(
            "evidence bundle hash payload must not contain secrets",
            code="secret_like_value",
        )
    return sha256_canonical(digest)


def build_research_evidence_bundle(
    session: Session,
    request: ResearchEvidenceBundleRequest,
) -> ResearchEvidenceBundleResult:
    """Coordinate local fixtures through research APIs. Does not trade."""
    settings = get_settings()
    mode = (
        settings.is_research_mode
        if request.research_mode is None
        else request.research_mode
    )
    stamp = request.created_at if request.created_at is not None else utc_now()
    if stamp.tzinfo is None:
        raise EvidenceBundleError(
            "created_at must be timezone-aware UTC",
            code="naive_timestamp",
        )
    stamp = stamp.astimezone(UTC)
    git_commit = request.git_commit
    if request.resolve_git and git_commit is None:
        git_commit = get_git_commit()
    output_dir = Path(request.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    steps: list[ResearchEvidenceBundleStep] = []
    warnings: list[ResearchEvidenceBundleIssue] = []
    errors: list[ResearchEvidenceBundleIssue] = []
    artifacts: list[ResearchEvidenceBundleArtifact] = list(default_evidence_artifacts())
    recorded: set[str] = set()

    snapshot_id: str | None = None
    replay_id: str | None = None
    backtest_id: str | None = None
    experiment_id: str | None = None
    snapshot_hash: str | None = None
    stream_hash: str | None = None
    backtest_hash: str | None = None
    experiment_hash: str | None = None
    report_hash: str | None = None
    release_report_hash: str | None = None
    normalized_dataset_hash: str | None = None
    normalized_dataset_id: str | None = None
    replay_ready: bool | None = None
    backtest_usable: bool | None = None
    experiment_usable: bool | None = None
    release_ok: bool | None = None
    alembic_head: str | None = None
    release_status: dict[str, object] | None = None
    policy_name = request.policy_name or "data_quality"
    failed = False
    fixture_data_mode: str | None = None
    fixture_reuse: EvidenceFixtureReuseReport | None = None

    def _ok(name: str, detail: str | None = None) -> None:
        steps.append(
            ResearchEvidenceBundleStep(name=name, status=STEP_STATUS_OK, detail=detail)
        )
        recorded.add(name)

    def _warn(name: str, code: str, message: str) -> None:
        warnings.append(
            ResearchEvidenceBundleIssue(
                severity="warning", code=code, message=message, step=name
            )
        )

    def _fail(name: str, code: str, message: str) -> NoReturn:
        raise _StepFailed(name, code, redact_secret_text(message))

    def _skip_remaining() -> None:
        for name in EVIDENCE_STEPS:
            if name in recorded or name == STEP_WRITE_MANIFEST:
                continue
            steps.append(
                ResearchEvidenceBundleStep(
                    name=name,
                    status=STEP_STATUS_SKIPPED,
                    detail="skipped after a previous step error",
                )
            )
            recorded.add(name)

    try:
        if not mode:
            _fail(
                STEP_VALIDATE_MODE, "app_mode_not_research", "APP_MODE must be research"
            )
        _ok(STEP_VALIDATE_MODE, "research")

        script_heads = alembic_script_heads()
        if script_heads != (EXPECTED_ALEMBIC_HEAD,):
            _fail(
                STEP_VALIDATE_ALEMBIC,
                "alembic_head_mismatch",
                "Alembic script head is not the expected research head",
            )
        db_head = session.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar()
        if db_head != EXPECTED_ALEMBIC_HEAD:
            _fail(
                STEP_VALIDATE_ALEMBIC,
                "alembic_head_mismatch",
                "database Alembic head is not the expected research head",
            )
        alembic_head = str(db_head)
        _ok(STEP_VALIDATE_ALEMBIC, alembic_head)

        if not is_registered_policy(policy_name):
            _fail(
                STEP_VALIDATE_POLICY,
                "invalid_policy",
                "policy is not a registered research policy",
            )
        try:
            get_research_policy(policy_name, request.policy_config)
        except BacktestError as exc:
            _fail(STEP_VALIDATE_POLICY, "invalid_policy", str(exc))
        _ok(STEP_VALIDATE_POLICY, policy_name)

        spec = _load_fixture_spec(request)
        source_name = request.source_name or spec.source_name
        reuse_candidate = existing_fixture_daily_bars_present(
            session, request.fixture_dir, source_name=source_name
        )
        skip_reference_writes = bool(
            request.allow_existing_fixture_data and reuse_candidate
        )
        if skip_reference_writes:
            _ok(STEP_LOAD_FIXTURES, "existing local CSV fixtures")
        else:
            _load_reference_tables(session, spec, request.fixture_dir)
            _ok(STEP_LOAD_FIXTURES, "local CSV fixtures")

        source, ingest, run = _ingest_bars(session, request, spec, source_name)
        if ingest.aborted:
            fixture_data_mode = EvidenceFixtureDataMode.FAILED.value
            fixture_reuse = empty_fixture_reuse_report(
                mode=EvidenceFixtureDataMode.FAILED.value
            )
            _fail(
                STEP_INGEST,
                "ingest_failed",
                "daily bar ingest did not insert research bars",
            )
        if ingest.inserted_bars > 0:
            fixture_data_mode = EvidenceFixtureDataMode.INSERTED.value
            fixture_reuse = empty_fixture_reuse_report(
                mode=EvidenceFixtureDataMode.INSERTED.value,
                inserted_bar_count=ingest.inserted_bars,
                inserted_corporate_action_count=fixture_csv_row_count(
                    request.fixture_dir / "corporate_actions.csv"
                ),
                inserted_session_count=fixture_csv_row_count(
                    request.fixture_dir / "sessions.csv"
                ),
            )
            if ingest.rejected_count:
                _warn(
                    STEP_INGEST,
                    "ingest_rejected_rows",
                    f"ingest rejected {ingest.rejected_count} rows",
                )
            session.flush()
            _ok(STEP_INGEST, f"inserted_bars={ingest.inserted_bars}")
            _ok(STEP_FIXTURE_DATA, EvidenceFixtureDataMode.INSERTED.value)
        elif request.allow_existing_fixture_data:
            reuse_report = check_existing_evidence_fixture_data(
                session, request.fixture_dir, source_name=source_name
            )
            if reuse_report.mode != EvidenceFixtureDataMode.REUSED.value:
                fixture_data_mode = EvidenceFixtureDataMode.FAILED.value
                fixture_reuse = reuse_report
                detail = "existing fixture data does not match"
                if reuse_report.issues:
                    detail = reuse_report.issues[0].message
                _fail(STEP_INGEST, "fixture_reuse_mismatch", detail)
            fixture_data_mode = EvidenceFixtureDataMode.REUSED.value
            fixture_reuse = reuse_report
            _warn(
                STEP_INGEST,
                "fixture_data_reused",
                "existing fixture data matched and was reused; no rows inserted",
            )
            session.flush()
            _ok(STEP_INGEST, f"reused_bars={reuse_report.reused_bar_count}")
            _ok(STEP_FIXTURE_DATA, EvidenceFixtureDataMode.REUSED.value)
        else:
            fixture_data_mode = EvidenceFixtureDataMode.FAILED.value
            fixture_reuse = empty_fixture_reuse_report(
                mode=EvidenceFixtureDataMode.FAILED.value
            )
            _fail(
                STEP_INGEST,
                "ingest_failed",
                "daily bar ingest did not insert research bars",
            )

        if fixture_data_mode == EvidenceFixtureDataMode.REUSED.value:
            correction_count = 0
        else:
            correction_count = _apply_corrections(
                session,
                request.fixture_dir / "corrections.csv",
                spec=spec,
                source_id=source.id,
                ingestion_run_id=run.id,
            )
        session.flush()
        _ok(STEP_CORRECTIONS, f"corrections={correction_count}")

        quality_request = build_dataset_quality_request(
            as_of=spec.as_of,
            start_time=spec.start_time,
            end_time=spec.end_time,
            symbols=spec.symbols,
            exchange_codes=spec.exchange_codes,
            asset_classes=(spec.asset_class,),
            currency=spec.currency,
            calendar_code=spec.calendar_code,
        )
        quality = get_dataset_quality_report(
            session, quality_request, generated_at=stamp
        )
        quality_dir = output_dir / REPORTS_DIRNAME
        write_dataset_quality_json(quality, quality_dir / "dataset_quality.json")
        artifacts.append(
            ResearchEvidenceBundleArtifact(
                name="dataset_quality",
                path=f"{REPORTS_DIRNAME}/dataset_quality.json",
                kind="json",
            )
        )
        if quality.error_count:
            _warn(
                STEP_QUALITY,
                "quality_errors",
                f"dataset quality reported {quality.error_count} errors",
            )
        _ok(
            STEP_QUALITY,
            f"rows={quality.total_rows} quality_hash={hash_quality_report(quality)}",
        )

        snapshot_request = build_dataset_snapshot_request(
            as_of=spec.as_of,
            start_time=spec.start_time,
            end_time=spec.end_time,
            symbols=spec.symbols,
            exchange_codes=spec.exchange_codes,
            asset_classes=(spec.asset_class,),
            currency=spec.currency,
            calendar_code=spec.calendar_code,
            notes=request.notes,
        )
        snapshot = create_daily_bars_snapshot(
            session,
            snapshot_request,
            output_dir / SNAPSHOT_DIRNAME,
            created_at=stamp,
            git_commit=git_commit,
            resolve_git=False,
        )
        snapshot_id = str(snapshot.manifest.snapshot_id)
        snapshot_hash = snapshot.manifest.content_hash
        artifacts.extend(
            (
                ResearchEvidenceBundleArtifact(
                    name="snapshot_manifest",
                    path=f"{SNAPSHOT_DIRNAME}/{MANIFEST_ARTIFACT_NAME}",
                    kind="json",
                ),
                ResearchEvidenceBundleArtifact(
                    name="snapshot_daily_bars",
                    path=f"{SNAPSHOT_DIRNAME}/{DAILY_BARS_ARTIFACT_NAME}",
                    kind="csv",
                ),
                ResearchEvidenceBundleArtifact(
                    name="snapshot_quality",
                    path=f"{SNAPSHOT_DIRNAME}/{QUALITY_ARTIFACT_NAME}",
                    kind="json",
                ),
            )
        )
        _ok(STEP_SNAPSHOT, snapshot_id)

        register_dataset_snapshot(session, snapshot.manifest)
        session.flush()
        _ok(STEP_CATALOG, snapshot_id)

        if (
            request.register_normalized_dataset
            and not request.include_normalized_dataset
        ):
            raise EvidenceBundleError(
                "register_normalized_dataset requires include_normalized_dataset",
                code="catalog_invalid",
            )
        if request.include_normalized_dataset:
            try:
                norm_request = build_normalization_request(
                    as_of=spec.as_of,
                    start_time=spec.start_time,
                    end_time=spec.end_time,
                    source_name=source_name,
                    adjustment_mode=request.normalization_adjustment_mode,
                    symbols=spec.symbols,
                    exchange_codes=spec.exchange_codes,
                    asset_classes=(spec.asset_class,),
                    currency=spec.currency,
                    calendar_code=spec.calendar_code,
                )
                normalized = build_normalized_daily_bars_dataset(session, norm_request)
                norm_dir = output_dir / NORMALIZED_DATASET_DIRNAME
                norm_manifest = write_normalized_dataset_artifacts(normalized, norm_dir)
                integrity = verify_normalization_artifacts(norm_dir)
                if not integrity.ok:
                    _fail(
                        STEP_NORMALIZATION,
                        "normalization_verify_failed",
                        "normalized dataset artifacts failed verification",
                    )
                normalized_dataset_hash = normalized.dataset_hash
                if request.register_normalized_dataset:
                    catalog_entry = build_normalized_dataset_registration(
                        normalized,
                        norm_manifest,
                        deterministic_id=request.deterministic_id,
                        source_type="snapshot",
                        source_snapshot_id=snapshot_id,
                        notes=request.notes,
                        created_at=stamp,
                    )
                    registration = register_normalized_dataset(session, catalog_entry)
                    session.flush()
                    catalog_usability = evaluate_normalized_dataset_usability(
                        session,
                        registration.entry.normalized_dataset_id,
                        norm_dir,
                    )
                    if not catalog_usability.usable:
                        _fail(
                            STEP_NORMALIZATION,
                            "catalog_not_usable",
                            "normalized dataset catalog row is not usable",
                        )
                    normalized_dataset_id = registration.entry.normalized_dataset_id
                artifacts.extend(
                    (
                        ResearchEvidenceBundleArtifact(
                            name="normalized_daily_bars",
                            path=(
                                f"{NORMALIZED_DATASET_DIRNAME}/"
                                f"{NORMALIZED_BARS_ARTIFACT_NAME}"
                            ),
                            kind="csv",
                        ),
                        ResearchEvidenceBundleArtifact(
                            name="normalization_report",
                            path=(
                                f"{NORMALIZED_DATASET_DIRNAME}/"
                                f"{NORMALIZATION_REPORT_NAME}"
                            ),
                            kind="json",
                        ),
                        ResearchEvidenceBundleArtifact(
                            name="normalization_manifest",
                            path=(
                                f"{NORMALIZED_DATASET_DIRNAME}/"
                                f"{NORMALIZATION_MANIFEST_NAME}"
                            ),
                            kind="json",
                        ),
                    )
                )
                _ok(STEP_NORMALIZATION, normalized_dataset_hash)
            except NormalizationError as exc:
                _fail(STEP_NORMALIZATION, exc.code, str(exc))

        dataset_request = snapshot_request.dataset
        replay = create_daily_bar_replay(
            session,
            dataset_request,
            include_corporate_actions=True,
            include_sessions=True,
            deterministic_id=request.deterministic_id,
        )
        audit = audit_replay(
            replay.events,
            as_of=replay.summary.as_of,
            sessions_requested=True,
            calendar_code=spec.calendar_code,
            start_time=spec.start_time,
        )
        if not audit.ok:
            _fail(
                STEP_REPLAY,
                "replay_audit_failed",
                "replay audit reported errors",
            )
        written_replay = write_replay_run_artifacts(
            replay,
            audit,
            output_dir / REPLAY_DIRNAME,
            request=dataset_request,
            notes=request.notes,
            dataset_snapshot_id=snapshot_id,
            created_at=stamp,
            git_commit=git_commit,
            resolve_git=False,
            include_sessions=True,
            include_corporate_actions=True,
        )
        register_replay_run(session, written_replay.manifest)
        session.flush()
        replay_id = str(written_replay.manifest.replay_id)
        stream_hash = written_replay.manifest.stream_hash
        artifacts.extend(
            (
                ResearchEvidenceBundleArtifact(
                    name="replay_manifest",
                    path=f"{REPLAY_DIRNAME}/{MANIFEST_ARTIFACT_NAME}",
                    kind="json",
                ),
                ResearchEvidenceBundleArtifact(
                    name="replay_events",
                    path=f"{REPLAY_DIRNAME}/{EVENTS_ARTIFACT_NAME}",
                    kind="jsonl",
                ),
                ResearchEvidenceBundleArtifact(
                    name="replay_audit",
                    path=f"{REPLAY_DIRNAME}/{AUDIT_ARTIFACT_NAME}",
                    kind="json",
                ),
                ResearchEvidenceBundleArtifact(
                    name="replay_summary",
                    path=f"{REPLAY_DIRNAME}/{SUMMARY_ARTIFACT_NAME}",
                    kind="json",
                ),
            )
        )
        _ok(STEP_REPLAY, replay_id)

        readiness = evaluate_replay_run_readiness(
            session,
            replay_id,
            output_dir / REPLAY_DIRNAME,
            research_mode=mode,
        )
        write_evidence_json(
            readiness.as_mapping(),
            output_dir / REPORTS_DIRNAME / "replay_readiness.json",
        )
        artifacts.append(
            ResearchEvidenceBundleArtifact(
                name="replay_readiness",
                path=f"{REPORTS_DIRNAME}/replay_readiness.json",
                kind="json",
            )
        )
        replay_ready = readiness.ready_for_backtest
        if not replay_ready:
            _fail(
                STEP_READINESS,
                "replay_not_ready",
                "replay run is not ready for a dry-run backtest",
            )
        _ok(STEP_READINESS, "ready_for_backtest")

        backtest_request = BacktestRequest(
            replay_id=replay_id,
            deterministic_id=request.deterministic_id,
            policy_name=policy_name,
            policy_config=request.policy_config,
            notes=request.notes,
        )
        backtest = run_backtest_from_replay_run(
            session,
            backtest_request,
            output_dir / REPLAY_DIRNAME,
            output_dir=output_dir / BACKTEST_DIRNAME,
            created_at=stamp,
            git_commit=git_commit,
            resolve_git=False,
            research_mode=mode,
        )
        if backtest.manifest is None:
            _fail(
                STEP_BACKTEST,
                "backtest_failed",
                "dry-run backtest did not write a manifest",
            )
        register_backtest_run(session, backtest.manifest)
        session.flush()
        backtest_id = str(backtest.summary.backtest_id)
        backtest_hash = backtest.summary.backtest_hash
        artifacts.extend(
            (
                ResearchEvidenceBundleArtifact(
                    name="backtest_manifest",
                    path=f"{BACKTEST_DIRNAME}/{BACKTEST_MANIFEST_NAME}",
                    kind="json",
                ),
                ResearchEvidenceBundleArtifact(
                    name="backtest_summary",
                    path=f"{BACKTEST_DIRNAME}/{BACKTEST_SUMMARY_NAME}",
                    kind="json",
                ),
                ResearchEvidenceBundleArtifact(
                    name="backtest_policy_output",
                    path=f"{BACKTEST_DIRNAME}/{POLICY_OUTPUT_ARTIFACT_NAME}",
                    kind="json",
                ),
            )
        )
        _ok(STEP_BACKTEST, backtest_id)

        usability = evaluate_backtest_result_usability(
            session,
            backtest_id,
            output_dir / BACKTEST_DIRNAME,
            research_mode=mode,
        )
        write_evidence_json(
            usability.as_mapping(),
            output_dir / REPORTS_DIRNAME / "backtest_usability.json",
        )
        artifacts.append(
            ResearchEvidenceBundleArtifact(
                name="backtest_usability",
                path=f"{REPORTS_DIRNAME}/backtest_usability.json",
                kind="json",
            )
        )
        backtest_usable = usability.usable_result
        if not backtest_usable:
            _fail(
                STEP_BACKTEST_USABILITY,
                "backtest_not_usable",
                "dry-run backtest is not usable research evidence",
            )
        _ok(STEP_BACKTEST_USABILITY, "usable_result")

        experiment_request = BacktestExperimentRequest(
            experiment_name=DEFAULT_EXPERIMENT_NAME,
            replay_ids=(replay_id,),
            policy_name=policy_name,
            policy_configs=(dict(request.policy_config or {}),),
            deterministic_ids=request.deterministic_id,
            notes=request.notes,
        )
        experiment = run_backtest_experiment(
            session,
            experiment_request,
            output_dir / REPLAY_DIRNAME,
            output_dir / EXPERIMENT_DIRNAME,
            register=True,
            created_at=stamp,
            git_commit=git_commit,
            resolve_git=False,
            research_mode=mode,
        )
        session.flush()
        experiment_id = experiment.summary.experiment_id
        experiment_hash = experiment.summary.experiment_hash
        artifacts.extend(
            (
                ResearchEvidenceBundleArtifact(
                    name="experiment_manifest",
                    path=f"{EXPERIMENT_DIRNAME}/{EXPERIMENT_MANIFEST_ARTIFACT_NAME}",
                    kind="json",
                ),
                ResearchEvidenceBundleArtifact(
                    name="experiment_summary",
                    path=f"{EXPERIMENT_DIRNAME}/{EXPERIMENT_SUMMARY_ARTIFACT_NAME}",
                    kind="json",
                ),
            )
        )
        _ok(STEP_EXPERIMENT, experiment_id)

        experiment_usability = evaluate_backtest_experiment_usability(
            session,
            experiment_id,
            output_dir / EXPERIMENT_DIRNAME,
            research_mode=mode,
        )
        write_evidence_json(
            experiment_usability.as_mapping(),
            output_dir / REPORTS_DIRNAME / "experiment_usability.json",
        )
        artifacts.append(
            ResearchEvidenceBundleArtifact(
                name="experiment_usability",
                path=f"{REPORTS_DIRNAME}/experiment_usability.json",
                kind="json",
            )
        )
        experiment_usable = experiment_usability.experiment_usable
        if not experiment_usable:
            _fail(
                STEP_EXPERIMENT_USABILITY,
                "experiment_not_usable",
                "experiment is not usable research evidence",
            )
        _ok(STEP_EXPERIMENT_USABILITY, "experiment_usable")

        if experiment.manifest is None:
            _fail(
                STEP_RESEARCH_REPORT,
                "experiment_manifest_missing",
                "experiment did not write a manifest",
            )
        entry = get_backtest_experiment_by_id(session, experiment_id)
        if entry is None:
            _fail(
                STEP_RESEARCH_REPORT,
                "experiment_catalog_missing",
                "experiment is not registered in the catalog",
            )
        members = members_from_experiment_summary(entry.summary)
        observations = load_member_observation_reports(
            output_dir / EXPERIMENT_DIRNAME, members
        )
        research_report = build_research_report_from_catalog(
            entry,
            observation_reports=observations,
            members=members,
        )
        write_backtest_experiment_report_artifacts(
            research_report,
            output_dir / EXPERIMENT_DIRNAME,
            usability=experiment_usability,
        )
        write_evidence_json(
            research_report.as_mapping(),
            output_dir / REPORTS_DIRNAME / "research_report.json",
        )
        report_hash = research_report.report_hash
        artifacts.extend(
            (
                ResearchEvidenceBundleArtifact(
                    name="experiment_research_report",
                    path=f"{EXPERIMENT_DIRNAME}/{EXPERIMENT_RESEARCH_REPORT_ARTIFACT_NAME}",
                    kind="json",
                ),
                ResearchEvidenceBundleArtifact(
                    name="experiment_usability_artifact",
                    path=f"{EXPERIMENT_DIRNAME}/{EXPERIMENT_USABILITY_ARTIFACT_NAME}",
                    kind="json",
                ),
                ResearchEvidenceBundleArtifact(
                    name="research_report",
                    path=f"{REPORTS_DIRNAME}/research_report.json",
                    kind="json",
                ),
            )
        )
        _ok(STEP_RESEARCH_REPORT, report_hash)

        release_report = run_research_release_checks(
            settings=settings,
            skip_db=request.skip_release_db,
            skip_compose=request.skip_compose,
            skip_regression=request.skip_regression,
            skip_normalization_regression=request.skip_normalization_regression,
            skip_data_contract_conformance=request.skip_data_contract_conformance,
            research_mode=mode,
        )
        release_status = without_local_paths(release_report.as_mapping())
        release_report_hash = release_report.report_hash or hash_release_status_report(
            release_report
        )
        release_ok = release_report.ok
        if not release_ok:
            _fail(
                STEP_RELEASE_STATUS,
                "release_check_failed",
                "research release check reported errors",
            )
        _ok(STEP_RELEASE_STATUS, release_report_hash)
    except _StepFailed as failed_step:
        failed = True
        steps.append(
            ResearchEvidenceBundleStep(
                name=failed_step.name,
                status=STEP_STATUS_ERROR,
                detail=failed_step.message,
            )
        )
        recorded.add(failed_step.name)
        errors.append(
            ResearchEvidenceBundleIssue(
                severity="error",
                code=failed_step.code,
                message=failed_step.message,
                step=failed_step.name,
            )
        )
        _skip_remaining()
    except (
        BacktestError,
        DatasetValidationError,
        SimulationError,
        DataValidationError,
        CsvLoadError,
        EvidenceBundleError,
        OSError,
        ValueError,
    ) as exc:
        failed = True
        code = getattr(exc, "code", "bundle_failed")
        message = redact_secret_text(str(exc))
        current = _current_step(recorded)
        steps.append(
            ResearchEvidenceBundleStep(
                name=current, status=STEP_STATUS_ERROR, detail=message
            )
        )
        recorded.add(current)
        errors.append(
            ResearchEvidenceBundleIssue(
                severity="error",
                code=str(code),
                message=message,
                step=current,
            )
        )
        _skip_remaining()

    ok = not failed and not errors
    draft = ResearchEvidenceBundleManifest(
        bundle_id="",
        created_at=stamp,
        package_version=__version__,
        git_commit=git_commit,
        app_mode="research" if mode else str(settings.app_mode),
        alembic_head=alembic_head,
        dataset_snapshot_id=snapshot_id,
        replay_id=replay_id,
        backtest_id=backtest_id,
        experiment_id=experiment_id,
        snapshot_hash=snapshot_hash,
        stream_hash=stream_hash,
        backtest_hash=backtest_hash,
        experiment_hash=experiment_hash,
        report_hash=report_hash,
        release_report_hash=release_report_hash,
        normalized_dataset_hash=normalized_dataset_hash,
        normalized_dataset_id=normalized_dataset_id,
        fixture_data_mode=fixture_data_mode,
        fixture_reuse=fixture_reuse,
        steps=tuple(steps),
        artifacts=_dedupe_artifacts(artifacts),
        warnings=tuple(warnings),
        errors=tuple(errors),
        ok=ok,
        bundle_hash="",
        replay_ready=replay_ready,
        backtest_usable=backtest_usable,
        experiment_usable=experiment_usable,
        release_ok=release_ok,
        policy_name=policy_name,
    )
    bundle_hash = hash_research_evidence_bundle(draft)
    bundle_id = _bundle_id(request.deterministic_id, bundle_hash)
    manifest = replace(draft, bundle_id=bundle_id, bundle_hash=bundle_hash)
    result = ResearchEvidenceBundleResult(
        request=request,
        manifest=manifest,
        output_dir=output_dir,
        release_status=release_status,
    )
    write_research_evidence_artifacts(result, release_status=release_status)
    steps.append(
        ResearchEvidenceBundleStep(
            name=STEP_WRITE_MANIFEST,
            status=STEP_STATUS_OK,
            detail=RELEASE_STATUS_NAME,
        )
    )
    recorded.add(STEP_WRITE_MANIFEST)
    manifest = replace(manifest, steps=tuple(steps))
    bundle_hash = hash_research_evidence_bundle(manifest)
    if request.deterministic_id:
        bundle_id = _bundle_id(True, bundle_hash)
    manifest = replace(manifest, bundle_id=bundle_id, bundle_hash=bundle_hash)
    result = ResearchEvidenceBundleResult(
        request=request,
        manifest=manifest,
        output_dir=output_dir,
        release_status=release_status,
    )
    write_research_evidence_artifacts(result, release_status=release_status)
    return result


def _bundle_id(deterministic: bool, bundle_hash: str) -> str:
    if not deterministic:
        return str(uuid4())
    digest = hashlib.sha256(bundle_hash.encode("utf-8")).digest()
    return str(UUID(bytes=digest[:16]))


def _current_step(recorded: set[str]) -> str:
    for name in EVIDENCE_STEPS:
        if name not in recorded:
            return name
    return STEP_WRITE_MANIFEST


def _dedupe_artifacts(
    artifacts: Sequence[ResearchEvidenceBundleArtifact],
) -> tuple[ResearchEvidenceBundleArtifact, ...]:
    seen: set[str] = set()
    rows: list[ResearchEvidenceBundleArtifact] = []
    for item in artifacts:
        if item.path in seen:
            continue
        seen.add(item.path)
        rows.append(item)
    return tuple(rows)


def _hash_source_mapping(
    value: (
        ResearchEvidenceBundleManifest
        | ResearchEvidenceBundleResult
        | Mapping[str, object]
    ),
) -> dict[str, object]:
    if isinstance(value, ResearchEvidenceBundleResult):
        payload = value.manifest.as_mapping(include_bundle_hash=False)
    elif isinstance(value, ResearchEvidenceBundleManifest):
        payload = value.as_mapping(include_bundle_hash=False)
    else:
        payload = dict(value)
    payload.pop("bundle_hash", None)
    payload.pop("created_at", None)
    payload.pop("bundle_id", None)
    payload.pop("git_commit", None)
    payload.pop("output_dir", None)
    return payload


def _load_fixture_spec(request: ResearchEvidenceBundleRequest) -> _FixtureSpec:
    fixture_dir = Path(request.fixture_dir)
    if not fixture_dir.is_dir():
        raise _StepFailed(
            STEP_LOAD_FIXTURES,
            "fixture_dir_missing",
            "fixture directory does not exist",
        )
    missing = [
        name for name in _REQUIRED_FIXTURES if not (fixture_dir / name).is_file()
    ]
    if missing:
        raise _StepFailed(
            STEP_LOAD_FIXTURES,
            "fixture_missing",
            f"missing fixture files: {', '.join(missing)}",
        )
    payload: dict[str, object] = {}
    spec_path = fixture_dir / "bundle.json"
    if spec_path.is_file():
        loaded = json.loads(spec_path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise _StepFailed(
                STEP_LOAD_FIXTURES,
                "invalid_fixture_spec",
                "bundle.json must be an object",
            )
        payload = loaded
    symbols = _string_tuple(payload.get("symbols"), default=("E2EA",))
    exchanges = _string_tuple(payload.get("exchange_codes"), default=("XE2E",))
    return _FixtureSpec(
        as_of=_parse_utc(payload.get("as_of"), default="2024-01-10T00:00:00+00:00"),
        start_time=_parse_utc(
            payload.get("start_time"), default="2024-01-01T00:00:00+00:00"
        ),
        end_time=_parse_utc(
            payload.get("end_time"), default="2024-01-08T00:00:00+00:00"
        ),
        symbols=symbols,
        exchange_codes=exchanges,
        calendar_code=str(payload.get("calendar_code") or "E2E_EQUITY"),
        asset_class=str(payload.get("asset_class") or "equity"),
        currency=str(payload.get("currency") or "USD"),
        source_name=str(payload.get("source_name") or "e2e_local_csv"),
        vendor=str(payload.get("vendor") or "local_csv"),
    )


def _string_tuple(value: object, *, default: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        return default
    rows = [str(item).strip() for item in value if str(item).strip()]
    return tuple(rows) if rows else default


def _parse_utc(value: object, *, default: str) -> datetime:
    raw = str(value).strip() if value is not None else default
    text = raw.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise _StepFailed(
            STEP_LOAD_FIXTURES,
            "naive_timestamp",
            "fixture timestamps must be timezone-aware UTC",
        )
    return parsed.astimezone(UTC)


def _load_reference_tables(
    session: Session, spec: _FixtureSpec, fixture_dir: Path
) -> None:
    load_exchanges_csv(session, fixture_dir / "exchanges.csv")
    load_calendars_csv(session, fixture_dir / "calendars.csv")
    load_sessions_csv(session, fixture_dir / "sessions.csv")
    load_corporate_actions_csv(session, fixture_dir / "corporate_actions.csv")
    calendar = get_market_calendar_by_code(session, code=spec.calendar_code)
    if calendar is None:
        raise _StepFailed(
            STEP_LOAD_FIXTURES,
            "calendar_missing",
            "fixture calendar was not loaded",
        )
    exchange = spec.exchange_codes[0] if spec.exchange_codes else None
    for symbol in spec.symbols:
        upsert_instrument(
            session,
            symbol=symbol,
            asset_class=spec.asset_class,
            currency=spec.currency,
            exchange=exchange,
            calendar_id=calendar.id,
        )
    session.flush()


def _ingest_bars(
    session: Session,
    request: ResearchEvidenceBundleRequest,
    spec: _FixtureSpec,
    source_name: str,
) -> tuple[DataSource, IngestResult, IngestionRun]:
    source = upsert_data_source(
        session,
        name=source_name,
        vendor=spec.vendor,
        description="local e2e research fixtures",
    )
    run = create_ingestion_run(
        session,
        source_id=source.id,
        run_metadata={"kind": "research_evidence_bundle"},
    )
    calendar = get_market_calendar_by_code(session, code=spec.calendar_code)
    exchange = spec.exchange_codes[0] if spec.exchange_codes else None
    ingest = ingest_daily_bars_csv(
        session,
        request.fixture_dir / "daily_bars.csv",
        source=source,
        run=run,
        asset_class=spec.asset_class,
        currency=spec.currency,
        exchange=exchange,
        error_mode=ErrorMode.COLLECT_ERRORS,
        validate_calendar=True,
        calendar_id=None if calendar is None else calendar.id,
    )
    finish_ingestion_run(
        session,
        run,
        status=(
            IngestionStatus.FAILED if ingest.aborted else IngestionStatus.SUCCEEDED
        ),
        row_count=ingest.accepted_count + ingest.rejected_count,
        accepted_count=ingest.accepted_count,
        rejected_count=ingest.rejected_count,
    )
    session.flush()
    return source, ingest, run


def _apply_corrections(
    session: Session,
    path: Path,
    *,
    spec: _FixtureSpec,
    source_id: UUID,
    ingestion_run_id: UUID,
) -> int:
    if not path.is_file():
        return 0
    count = 0
    exchange = spec.exchange_codes[0] if spec.exchange_codes else None
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            symbol = (row.get("symbol") or "").strip()
            instrument = upsert_instrument(
                session,
                symbol=symbol,
                asset_class=spec.asset_class,
                currency=spec.currency,
                exchange=exchange,
            )
            observation = parse_observation_time(row["date"])
            available = parse_utc_datetime(
                row["available_time"], field="available_time"
            )
            bars = get_daily_bars(
                session, instrument_id=instrument.id, source_id=source_id
            )
            original = next(
                (
                    item
                    for item in bars
                    if item.observation_time == observation and not item.is_correction
                ),
                None,
            )
            if original is None:
                raise _StepFailed(
                    STEP_CORRECTIONS,
                    "correction_original_missing",
                    f"no original bar found for {symbol}",
                )
            already = next(
                (
                    item
                    for item in bars
                    if item.observation_time == observation
                    and item.available_time == available
                    and item.is_correction
                ),
                None,
            )
            if already is not None:
                continue
            insert_daily_bar_correction(
                session,
                superseded=original,
                available_time=available,
                open=parse_decimal(row["open"], field="open"),
                high=parse_decimal(row["high"], field="high"),
                low=parse_decimal(row["low"], field="low"),
                close=parse_decimal(row["close"], field="close"),
                volume=parse_decimal(row["volume"], field="volume")
                if (row.get("volume") or "").strip()
                else None,
                ingestion_run_id=ingestion_run_id,
                reason=(row.get("reason") or "late_print").strip() or "late_print",
            )
            count += 1
    return count
