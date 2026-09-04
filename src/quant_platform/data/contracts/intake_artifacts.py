"""Local contract-payload intake artifacts. Relative paths only; no secrets."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from quant_platform.data.contracts.errors import (
    VendorContractError,
    VendorContractErrorCode,
)
from quant_platform.data.contracts.hashing import jsonable_vendor_payload
from quant_platform.data.contracts.intake import (
    build_contract_payload_intake_plan,
    build_contract_payload_intake_report,
)
from quant_platform.data.contracts.intake_types import (
    INTAKE_MANIFEST_ARTIFACT_NAME,
    INTAKE_PLAN_ARTIFACT_NAME,
    INTAKE_REPORT_ARTIFACT_NAME,
    INTAKE_SOURCE_BATCH_ARTIFACT_NAME,
    ContractPayloadIntakeManifest,
    ContractPayloadIntakePlan,
    ContractPayloadIntakeReport,
    ContractPayloadIntakeRequest,
    default_intake_artifacts,
)
from quant_platform.data.contracts.types import VendorPayloadBatch
from quant_platform.simulation.run_types import artifact_path_is_unsafe

_SECRET_MARKERS = (
    "DATABASE_URL",
    "POSTGRES_PASSWORD",
    "postgresql://",
    "postgres://",
    "postgresql+psycopg://",
)


def write_contract_payload_intake_artifacts(
    plan: ContractPayloadIntakePlan,
    report: ContractPayloadIntakeReport,
    output_dir: Path | str,
    *,
    batch: VendorPayloadBatch | None = None,
    include_source_payload: bool = False,
) -> ContractPayloadIntakeManifest:
    """Write plan/report/manifest JSON. Optional source batch. No PostgreSQL."""
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    artifacts = default_intake_artifacts(include_source_payload=include_source_payload)
    for item in artifacts:
        if artifact_path_is_unsafe(item.path):
            raise VendorContractError(
                "intake artifact paths must be relative",
                code=VendorContractErrorCode.VALIDATION_ERROR,
            )
    _write_json(plan.as_mapping(), root / INTAKE_PLAN_ARTIFACT_NAME)
    _write_json(report.as_mapping(), root / INTAKE_REPORT_ARTIFACT_NAME)
    if include_source_payload:
        if batch is None:
            raise VendorContractError(
                "source payload artifact requires a batch",
                code=VendorContractErrorCode.VALIDATION_ERROR,
            )
        _write_json(
            {
                "kind": "vendor_payload_batch",
                "batch": jsonable_vendor_payload(batch.as_mapping()),
            },
            root / INTAKE_SOURCE_BATCH_ARTIFACT_NAME,
        )
    manifest = ContractPayloadIntakeManifest(
        source_name=report.source_name,
        contract_name=report.contract_name,
        contract_version=report.contract_version,
        batch_hash=report.batch_hash,
        conformance_hash=report.conformance_hash,
        intake_hash=report.intake_hash,
        write_db=report.write_db,
        db_executed=report.db_executed,
        ok=report.ok,
        payload_counts=report.payload_counts,
        accepted_counts=report.accepted_counts,
        rejected_counts=report.rejected_counts,
        inserted_counts=report.inserted_counts,
        skipped_counts=report.skipped_counts,
        issue_count=len(report.issues),
        artifacts=artifacts,
    )
    _write_json(manifest.as_mapping(), root / INTAKE_MANIFEST_ARTIFACT_NAME)
    return manifest


def write_intake_artifacts_from_batch(
    batch: VendorPayloadBatch,
    output_dir: Path | str,
    *,
    request: ContractPayloadIntakeRequest | None = None,
    report: ContractPayloadIntakeReport | None = None,
) -> ContractPayloadIntakeManifest:
    """Build a dry-run plan/report and write artifacts. Offline only."""
    req = request
    plan = build_contract_payload_intake_plan(batch, req)
    built = report if report is not None else build_contract_payload_intake_report(plan)
    include = False if req is None else req.include_source_payload
    return write_contract_payload_intake_artifacts(
        plan,
        built,
        output_dir,
        batch=batch,
        include_source_payload=include,
    )


def _write_json(payload: Mapping[str, object], path: Path) -> None:
    if artifact_path_is_unsafe(path.name):
        raise VendorContractError(
            "intake artifact paths must be relative",
            code=VendorContractErrorCode.VALIDATION_ERROR,
        )
    converted = jsonable_vendor_payload(dict(payload))
    if not isinstance(converted, dict):
        raise VendorContractError(
            "intake artifact JSON must be an object",
            code=VendorContractErrorCode.VALIDATION_ERROR,
        )
    text = json.dumps(converted, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    lowered = text.lower()
    for marker in _SECRET_MARKERS:
        if marker.lower() in lowered:
            raise VendorContractError(
                "intake artifacts must not contain secrets",
                code=VendorContractErrorCode.SECRET_IN_METADATA,
            )
    path.write_text(text, encoding="utf-8")
