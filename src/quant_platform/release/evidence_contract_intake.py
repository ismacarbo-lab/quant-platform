"""Opt-in offline contract-payload intake for the research evidence bundle.

This is not a vendor client, download path, or trading step.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from quant_platform.data.contracts.errors import VendorContractError
from quant_platform.data.contracts.fake_provider import (
    load_offline_vendor_payload_batch,
)
from quant_platform.data.contracts.intake import (
    build_contract_payload_intake_plan,
    build_contract_payload_intake_report,
    build_contract_payload_intake_request,
    execute_contract_payload_intake,
)
from quant_platform.data.contracts.intake_artifacts import (
    write_contract_payload_intake_artifacts,
)
from quant_platform.data.contracts.intake_integrity import (
    verify_contract_payload_intake_artifacts,
)
from quant_platform.data.contracts.intake_regression import (
    default_contract_payload_intake_dir,
)
from quant_platform.data.contracts.intake_regression_types import BATCH_FIXTURE_NAME
from quant_platform.data.contracts.intake_types import (
    INTAKE_MANIFEST_ARTIFACT_NAME,
    INTAKE_PLAN_ARTIFACT_NAME,
    INTAKE_REPORT_ARTIFACT_NAME,
    ContractPayloadIntakeCounts,
    ContractPayloadIntakeReport,
)
from quant_platform.data.models import DailyBar
from quant_platform.release.evidence_types import (
    CONTRACT_INTAKE_ARTIFACT_STATUS_OK,
    CONTRACT_INTAKE_DB_STATUS_EXECUTED,
    CONTRACT_INTAKE_DB_STATUS_NOT_EXECUTED,
    CONTRACT_INTAKE_STATUS_DRY_RUN,
    CONTRACT_INTAKE_STATUS_WRITTEN,
    DEFAULT_CONTRACT_INTAKE_FIXTURE_CASE,
    DEFAULT_CONTRACT_INTAKE_OUTPUT_DIR_NAME,
    EvidenceBundleError,
    ResearchEvidenceBundleArtifact,
    ResearchEvidenceBundleRequest,
)
from quant_platform.simulation.run_types import artifact_path_is_unsafe

_EVIDENCE_INTAKE_CREATED_BY = "research_evidence_bundle"


@dataclass(frozen=True, slots=True)
class EvidenceContractIntakeOutcome:
    included: bool
    write_db: bool
    status: str
    artifact_status: str
    db_status: str
    intake_hash: str
    batch_hash: str
    inserted_counts: dict[str, int]
    skipped_counts: dict[str, int]
    artifacts: tuple[ResearchEvidenceBundleArtifact, ...]
    report: ContractPayloadIntakeReport
    output_dir_name: str


def intake_counts_payload(counts: ContractPayloadIntakeCounts) -> dict[str, int]:
    return {
        "daily_bars": counts.daily_bars,
        "corporate_actions": counts.corporate_actions,
        "market_sessions": counts.market_sessions,
        "total": counts.total,
    }


def evidence_daily_bar_fingerprint(
    session: Session, *, source_id: UUID
) -> tuple[tuple[object, ...], ...]:
    rows = session.scalars(
        select(DailyBar)
        .where(DailyBar.source_id == source_id)
        .order_by(DailyBar.id, DailyBar.observation_time, DailyBar.available_time)
    ).all()
    return tuple(
        (
            row.id,
            row.open,
            row.high,
            row.low,
            row.close,
            row.volume,
            row.available_time,
            row.observation_time,
            row.is_correction,
        )
        for row in rows
    )


def resolve_evidence_contract_intake_batch_path(
    request: ResearchEvidenceBundleRequest,
) -> Path:
    """Resolve a local batch JSON path. Never opens a network connection."""
    if (
        request.contract_intake_batch_file is not None
        and request.contract_intake_fixture_dir is not None
    ):
        raise EvidenceBundleError(
            "specify only one of contract_intake_batch_file or "
            "contract_intake_fixture_dir",
            code="contract_intake_source_ambiguous",
        )
    if request.contract_intake_batch_file is not None:
        path = Path(request.contract_intake_batch_file)
        if not path.is_file():
            raise EvidenceBundleError(
                "contract intake batch file is missing",
                code="contract_intake_batch_missing",
            )
        return path
    if request.contract_intake_fixture_dir is not None:
        path = Path(request.contract_intake_fixture_dir) / BATCH_FIXTURE_NAME
        if not path.is_file():
            raise EvidenceBundleError(
                "contract intake fixture directory has no batch.json",
                code="contract_intake_batch_missing",
            )
        return path
    default_dir = (
        default_contract_payload_intake_dir() / DEFAULT_CONTRACT_INTAKE_FIXTURE_CASE
    )
    path = default_dir / BATCH_FIXTURE_NAME
    if not path.is_file():
        raise EvidenceBundleError(
            "default contract intake fixture is missing",
            code="contract_intake_batch_missing",
        )
    return path


def resolve_evidence_contract_intake_output_dir_name(
    request: ResearchEvidenceBundleRequest,
) -> str:
    name = (
        request.contract_intake_output_dir_name.strip()
        or DEFAULT_CONTRACT_INTAKE_OUTPUT_DIR_NAME
    )
    cleaned = name.replace("\\", "/")
    if (
        artifact_path_is_unsafe(cleaned)
        or "/" in cleaned
        or cleaned in {".", ".."}
        or not cleaned
    ):
        raise EvidenceBundleError(
            "contract intake output directory name must be a relative folder",
            code="absolute_path",
        )
    return cleaned


def run_evidence_contract_payload_intake(
    request: ResearchEvidenceBundleRequest,
    output_dir: Path,
    *,
    session: Session | None = None,
    evidence_source_id: UUID | None = None,
) -> EvidenceContractIntakeOutcome:
    """Plan, optionally write, and store intake artifacts. Offline only."""
    if not request.include_contract_payload_intake:
        raise EvidenceBundleError(
            "contract payload intake was not requested",
            code="contract_intake_not_requested",
        )
    if request.contract_intake_write_db and session is None:
        raise EvidenceBundleError(
            "contract intake write_db requires a database session",
            code="contract_intake_session_required",
        )
    dirname = resolve_evidence_contract_intake_output_dir_name(request)
    batch_path = resolve_evidence_contract_intake_batch_path(request)
    try:
        batch = load_offline_vendor_payload_batch(batch_path)
        intake_request = build_contract_payload_intake_request(
            source_name=batch.source_name,
            created_by=_EVIDENCE_INTAKE_CREATED_BY,
            write_db=request.contract_intake_write_db,
        )
        if request.contract_intake_write_db:
            if session is None:
                raise EvidenceBundleError(
                    "contract intake write_db requires a database session",
                    code="contract_intake_session_required",
                )
            db_session = session
            before = (
                evidence_daily_bar_fingerprint(db_session, source_id=evidence_source_id)
                if evidence_source_id is not None
                else ()
            )
            report = execute_contract_payload_intake(db_session, batch, intake_request)
            after = (
                evidence_daily_bar_fingerprint(db_session, source_id=evidence_source_id)
                if evidence_source_id is not None
                else ()
            )
            if evidence_source_id is not None and before != after:
                raise EvidenceBundleError(
                    "contract intake must not rewrite existing evidence daily_bars",
                    code="daily_bars_mutated",
                )
            plan = build_contract_payload_intake_plan(batch, intake_request)
        else:
            plan = build_contract_payload_intake_plan(batch, intake_request)
            report = build_contract_payload_intake_report(plan)
    except VendorContractError as exc:
        raise EvidenceBundleError(str(exc), code=str(exc.code)) from exc
    if not plan.ok or not report.ok:
        raise EvidenceBundleError(
            "contract payload intake plan is not ok",
            code="contract_intake_failed",
        )
    if not request.contract_intake_write_db and report.inserted_counts.total != 0:
        raise EvidenceBundleError(
            "dry-run contract intake must not insert rows",
            code="contract_intake_write_mismatch",
        )
    target = Path(output_dir) / dirname
    write_contract_payload_intake_artifacts(plan, report, target)
    integrity = verify_contract_payload_intake_artifacts(target)
    if not integrity.ok:
        raise EvidenceBundleError(
            "contract intake artifacts failed verification",
            code="contract_intake_verify_failed",
        )
    artifacts = (
        ResearchEvidenceBundleArtifact(
            name="contract_payload_intake_plan",
            path=f"{dirname}/{INTAKE_PLAN_ARTIFACT_NAME}",
            kind="json",
        ),
        ResearchEvidenceBundleArtifact(
            name="contract_payload_intake_report",
            path=f"{dirname}/{INTAKE_REPORT_ARTIFACT_NAME}",
            kind="json",
        ),
        ResearchEvidenceBundleArtifact(
            name="contract_payload_intake_manifest",
            path=f"{dirname}/{INTAKE_MANIFEST_ARTIFACT_NAME}",
            kind="json",
        ),
    )
    write_db = bool(request.contract_intake_write_db)
    return EvidenceContractIntakeOutcome(
        included=True,
        write_db=write_db,
        status=(
            CONTRACT_INTAKE_STATUS_WRITTEN
            if write_db and report.db_executed
            else CONTRACT_INTAKE_STATUS_DRY_RUN
        ),
        artifact_status=CONTRACT_INTAKE_ARTIFACT_STATUS_OK,
        db_status=(
            CONTRACT_INTAKE_DB_STATUS_EXECUTED
            if report.db_executed
            else CONTRACT_INTAKE_DB_STATUS_NOT_EXECUTED
        ),
        intake_hash=report.intake_hash,
        batch_hash=report.batch_hash,
        inserted_counts=intake_counts_payload(report.inserted_counts),
        skipped_counts=intake_counts_payload(report.skipped_counts),
        artifacts=artifacts,
        report=report,
        output_dir_name=dirname,
    )
