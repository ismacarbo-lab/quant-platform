"""Local data-contract conformance artifacts. Relative paths only; no secrets."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from quant_platform.data.contracts.conformance import (
    build_data_contract_conformance_report,
)
from quant_platform.data.contracts.conformance_types import (
    CONFORMANCE_MANIFEST_ARTIFACT_NAME,
    CONFORMANCE_REPORT_ARTIFACT_NAME,
    CONFORMANCE_SOURCE_BATCH_ARTIFACT_NAME,
    DataContractConformanceManifest,
    DataContractConformanceReport,
    DataContractConformanceRequest,
    default_conformance_artifacts,
)
from quant_platform.data.contracts.errors import (
    VendorContractError,
    VendorContractErrorCode,
)
from quant_platform.data.contracts.hashing import jsonable_vendor_payload
from quant_platform.data.contracts.types import VendorPayloadBatch
from quant_platform.simulation.run_types import artifact_path_is_unsafe

_SECRET_MARKERS = (
    "DATABASE_URL",
    "POSTGRES_PASSWORD",
    "postgresql://",
    "postgres://",
    "postgresql+psycopg://",
)


def write_data_contract_conformance_artifacts(
    report: DataContractConformanceReport,
    output_dir: Path | str,
    *,
    batch: VendorPayloadBatch | None = None,
    include_source_payload: bool = False,
) -> DataContractConformanceManifest:
    """Write report/manifest JSON. Optional source batch. No PostgreSQL."""
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    artifacts = default_conformance_artifacts(
        include_source_payload=include_source_payload
    )
    for item in artifacts:
        if artifact_path_is_unsafe(item.path):
            raise VendorContractError(
                "conformance artifact paths must be relative",
                code=VendorContractErrorCode.VALIDATION_ERROR,
            )
    report_path = root / CONFORMANCE_REPORT_ARTIFACT_NAME
    manifest_path = root / CONFORMANCE_MANIFEST_ARTIFACT_NAME
    _write_json(report.as_mapping(), report_path)
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
            root / CONFORMANCE_SOURCE_BATCH_ARTIFACT_NAME,
        )
    manifest = DataContractConformanceManifest(
        contract_name=report.summary.contract_name,
        contract_version=report.summary.contract_version,
        source_name=report.summary.source_name,
        batch_hash=report.summary.batch_hash,
        conformance_hash=report.conformance_hash,
        payload_counts=report.summary.payload_counts,
        issue_count=report.summary.issue_counts.total,
        validation_ok=report.summary.validation_ok,
        forbidden_terms_ok=report.summary.forbidden_terms_ok,
        offline_only_ok=report.summary.offline_only_ok,
        artifacts=artifacts,
    )
    _write_json(manifest.as_mapping(), manifest_path)
    return manifest


def write_conformance_report_from_batch(
    batch: VendorPayloadBatch,
    output_dir: Path | str,
    *,
    request: DataContractConformanceRequest | None = None,
) -> DataContractConformanceManifest:
    """Build a report and write artifacts. Offline only."""
    req = request
    report = build_data_contract_conformance_report(batch, req)
    include = False if req is None else req.include_source_payload
    return write_data_contract_conformance_artifacts(
        report,
        output_dir,
        batch=batch,
        include_source_payload=include,
    )


def _write_json(payload: Mapping[str, object], path: Path) -> None:
    if artifact_path_is_unsafe(path.name):
        raise VendorContractError(
            "conformance artifact paths must be relative",
            code=VendorContractErrorCode.VALIDATION_ERROR,
        )
    converted = jsonable_vendor_payload(dict(payload))
    if not isinstance(converted, dict):
        raise VendorContractError(
            "conformance artifact JSON must be an object",
            code=VendorContractErrorCode.VALIDATION_ERROR,
        )
    text = json.dumps(converted, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    lowered = text.lower()
    for marker in _SECRET_MARKERS:
        if marker.lower() in lowered:
            raise VendorContractError(
                "conformance artifacts must not contain secrets",
                code=VendorContractErrorCode.SECRET_IN_METADATA,
            )
    path.write_text(text, encoding="utf-8")
