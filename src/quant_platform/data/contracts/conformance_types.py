"""Typed data-contract conformance reports. Not a vendor client or PnL check."""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_CONTRACT_NAME = "vendor_agnostic_data_source"
DEFAULT_CONTRACT_VERSION = "1"
DEFAULT_CREATED_BY = "offline_conformance_runner"

CONFORMANCE_REPORT_KIND = "data_contract_conformance_report"
CONFORMANCE_REPORT_FORMAT_VERSION = 1
CONFORMANCE_HASH_KIND = "data_contract_conformance_report"
CONFORMANCE_HASH_FORMAT_VERSION = 1
CONFORMANCE_MANIFEST_KIND = "data_contract_conformance_manifest"
CONFORMANCE_MANIFEST_FORMAT_VERSION = 1

CONFORMANCE_REPORT_ARTIFACT_NAME = "data_contract_conformance_report.json"
CONFORMANCE_MANIFEST_ARTIFACT_NAME = "data_contract_conformance_manifest.json"
CONFORMANCE_SOURCE_BATCH_ARTIFACT_NAME = "source_payload_batch.json"


@dataclass(frozen=True, slots=True)
class DataContractConformanceRequest:
    contract_name: str = DEFAULT_CONTRACT_NAME
    contract_version: str = DEFAULT_CONTRACT_VERSION
    source_name: str | None = None
    created_by: str = DEFAULT_CREATED_BY
    notes: str | None = None
    include_source_payload: bool = False

    def as_mapping(self) -> dict[str, object]:
        return {
            "contract_name": self.contract_name,
            "contract_version": self.contract_version,
            "source_name": self.source_name,
            "created_by": self.created_by,
            "notes": self.notes,
            "include_source_payload": self.include_source_payload,
        }


@dataclass(frozen=True, slots=True)
class DataContractConformanceIssue:
    code: str
    message: str
    field: str | None = None
    record_kind: str | None = None
    record_index: int | None = None

    def as_mapping(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "field": self.field,
            "record_kind": self.record_kind,
            "record_index": self.record_index,
        }


@dataclass(frozen=True, slots=True)
class DataContractPayloadCounts:
    daily_bars: int
    corporate_actions: int
    market_sessions: int

    @property
    def total(self) -> int:
        return self.daily_bars + self.corporate_actions + self.market_sessions

    def as_mapping(self) -> dict[str, object]:
        return {
            "daily_bars": self.daily_bars,
            "corporate_actions": self.corporate_actions,
            "market_sessions": self.market_sessions,
            "total": self.total,
        }


@dataclass(frozen=True, slots=True)
class DataContractIssueCounts:
    total: int
    by_code: tuple[tuple[str, int], ...]

    def as_mapping(self) -> dict[str, object]:
        return {
            "total": self.total,
            "by_code": {code: count for code, count in self.by_code},
        }


@dataclass(frozen=True, slots=True)
class DataContractConformanceSummary:
    contract_name: str
    contract_version: str
    source_name: str
    batch_hash: str
    payload_counts: DataContractPayloadCounts
    issue_counts: DataContractIssueCounts
    capability_summary: tuple[str, ...]
    validation_ok: bool
    forbidden_terms_ok: bool
    offline_only_ok: bool

    def as_mapping(self) -> dict[str, object]:
        return {
            "contract_name": self.contract_name,
            "contract_version": self.contract_version,
            "source_name": self.source_name,
            "batch_hash": self.batch_hash,
            "payload_counts": self.payload_counts.as_mapping(),
            "issue_counts": self.issue_counts.as_mapping(),
            "capability_summary": list(self.capability_summary),
            "validation_ok": self.validation_ok,
            "forbidden_terms_ok": self.forbidden_terms_ok,
            "offline_only_ok": self.offline_only_ok,
        }


@dataclass(frozen=True, slots=True)
class DataContractConformanceReport:
    ok: bool
    summary: DataContractConformanceSummary
    issues: tuple[DataContractConformanceIssue, ...]
    created_by: str
    notes: str | None
    conformance_hash: str

    def as_mapping(self, *, include_conformance_hash: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "kind": CONFORMANCE_REPORT_KIND,
            "format_version": CONFORMANCE_REPORT_FORMAT_VERSION,
            "ok": self.ok,
            "summary": self.summary.as_mapping(),
            "issues": [item.as_mapping() for item in self.issues],
            "created_by": self.created_by,
            "notes": self.notes,
        }
        if include_conformance_hash:
            payload["conformance_hash"] = self.conformance_hash
        return payload


@dataclass(frozen=True, slots=True)
class DataContractConformanceArtifact:
    name: str
    path: str
    kind: str = "json"

    def as_mapping(self) -> dict[str, object]:
        return {"name": self.name, "path": self.path, "kind": self.kind}


@dataclass(frozen=True, slots=True)
class DataContractConformanceIntegrityReport:
    ok: bool
    issues: tuple[DataContractConformanceIssue, ...]
    error_count: int

    def as_mapping(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "error_count": self.error_count,
            "issues": [item.as_mapping() for item in self.issues],
        }


@dataclass(frozen=True, slots=True)
class DataContractConformanceManifest:
    contract_name: str
    contract_version: str
    source_name: str
    batch_hash: str
    conformance_hash: str
    payload_counts: DataContractPayloadCounts
    issue_count: int
    validation_ok: bool
    forbidden_terms_ok: bool
    offline_only_ok: bool
    artifacts: tuple[DataContractConformanceArtifact, ...]

    def as_mapping(self) -> dict[str, object]:
        return {
            "kind": CONFORMANCE_MANIFEST_KIND,
            "format_version": CONFORMANCE_MANIFEST_FORMAT_VERSION,
            "contract_name": self.contract_name,
            "contract_version": self.contract_version,
            "source_name": self.source_name,
            "batch_hash": self.batch_hash,
            "conformance_hash": self.conformance_hash,
            "payload_counts": self.payload_counts.as_mapping(),
            "issue_count": self.issue_count,
            "validation_ok": self.validation_ok,
            "forbidden_terms_ok": self.forbidden_terms_ok,
            "offline_only_ok": self.offline_only_ok,
            "artifacts": [item.as_mapping() for item in self.artifacts],
        }


def default_conformance_artifacts(
    *,
    include_source_payload: bool = False,
) -> tuple[DataContractConformanceArtifact, ...]:
    artifacts: tuple[DataContractConformanceArtifact, ...] = (
        DataContractConformanceArtifact(
            name="report",
            path=CONFORMANCE_REPORT_ARTIFACT_NAME,
        ),
        DataContractConformanceArtifact(
            name="manifest",
            path=CONFORMANCE_MANIFEST_ARTIFACT_NAME,
        ),
    )
    if include_source_payload:
        artifacts = (
            *artifacts,
            DataContractConformanceArtifact(
                name="source_payload_batch",
                path=CONFORMANCE_SOURCE_BATCH_ARTIFACT_NAME,
            ),
        )
    return artifacts
