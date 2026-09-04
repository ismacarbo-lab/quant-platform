"""Typed offline contract payload intake records. Not a vendor client or PnL check."""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_CONTRACT_NAME = "vendor_agnostic_data_source"
DEFAULT_CONTRACT_VERSION = "1"
DEFAULT_CREATED_BY = "offline_intake_runner"
DEFAULT_ASSET_CLASS = "equity"
OFFLINE_SOURCE_VENDOR_LABEL = "offline_contract"

INTAKE_PLAN_KIND = "contract_payload_intake_plan"
INTAKE_PLAN_FORMAT_VERSION = 1
INTAKE_PLAN_HASH_KIND = "contract_payload_intake_plan"
INTAKE_PLAN_HASH_FORMAT_VERSION = 1
INTAKE_REPORT_KIND = "contract_payload_intake_report"
INTAKE_REPORT_FORMAT_VERSION = 1
INTAKE_REPORT_HASH_KIND = "contract_payload_intake_report"
INTAKE_REPORT_HASH_FORMAT_VERSION = 1
INTAKE_MANIFEST_KIND = "contract_payload_intake_manifest"
INTAKE_MANIFEST_FORMAT_VERSION = 1

INTAKE_PLAN_ARTIFACT_NAME = "contract_payload_intake_plan.json"
INTAKE_REPORT_ARTIFACT_NAME = "contract_payload_intake_report.json"
INTAKE_MANIFEST_ARTIFACT_NAME = "contract_payload_intake_manifest.json"
INTAKE_SOURCE_BATCH_ARTIFACT_NAME = "source_payload_batch.json"

RECORD_KIND_DAILY_BAR = "daily_bar"
RECORD_KIND_CORPORATE_ACTION = "corporate_action"
RECORD_KIND_MARKET_SESSION = "market_session"


@dataclass(frozen=True, slots=True)
class ContractPayloadIntakeCounts:
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
class ContractPayloadIntakeRequest:
    contract_name: str = DEFAULT_CONTRACT_NAME
    contract_version: str = DEFAULT_CONTRACT_VERSION
    source_name: str | None = None
    created_by: str = DEFAULT_CREATED_BY
    notes: str | None = None
    write_db: bool = False
    allow_invalid: bool = False
    include_source_payload: bool = False
    asset_class: str = DEFAULT_ASSET_CLASS

    def as_mapping(self) -> dict[str, object]:
        return {
            "contract_name": self.contract_name,
            "contract_version": self.contract_version,
            "source_name": self.source_name,
            "created_by": self.created_by,
            "notes": self.notes,
            "write_db": self.write_db,
            "allow_invalid": self.allow_invalid,
            "include_source_payload": self.include_source_payload,
            "asset_class": self.asset_class,
        }


@dataclass(frozen=True, slots=True)
class ContractPayloadIntakeIssue:
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
class ContractPayloadIntakeItem:
    record_kind: str
    record_index: int
    accepted: bool
    payload_hash: str
    symbol: str | None = None
    skip_reason: str | None = None

    def as_mapping(self) -> dict[str, object]:
        return {
            "record_kind": self.record_kind,
            "record_index": self.record_index,
            "accepted": self.accepted,
            "payload_hash": self.payload_hash,
            "symbol": self.symbol,
            "skip_reason": self.skip_reason,
        }


@dataclass(frozen=True, slots=True)
class ContractPayloadIntakePlan:
    ok: bool
    source_name: str
    contract_name: str
    contract_version: str
    batch_hash: str
    conformance_hash: str
    write_db: bool
    allow_invalid: bool
    payload_counts: ContractPayloadIntakeCounts
    accepted_counts: ContractPayloadIntakeCounts
    rejected_counts: ContractPayloadIntakeCounts
    planned_daily_bar_count: int
    planned_corporate_action_count: int
    planned_market_session_count: int
    items: tuple[ContractPayloadIntakeItem, ...]
    issues: tuple[ContractPayloadIntakeIssue, ...]
    warnings: tuple[ContractPayloadIntakeIssue, ...]
    created_by: str
    notes: str | None
    intake_hash: str

    def as_mapping(self, *, include_intake_hash: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "kind": INTAKE_PLAN_KIND,
            "format_version": INTAKE_PLAN_FORMAT_VERSION,
            "ok": self.ok,
            "source_name": self.source_name,
            "contract_name": self.contract_name,
            "contract_version": self.contract_version,
            "batch_hash": self.batch_hash,
            "conformance_hash": self.conformance_hash,
            "write_db": self.write_db,
            "allow_invalid": self.allow_invalid,
            "payload_counts": self.payload_counts.as_mapping(),
            "accepted_counts": self.accepted_counts.as_mapping(),
            "rejected_counts": self.rejected_counts.as_mapping(),
            "planned_daily_bar_count": self.planned_daily_bar_count,
            "planned_corporate_action_count": self.planned_corporate_action_count,
            "planned_market_session_count": self.planned_market_session_count,
            "items": [item.as_mapping() for item in self.items],
            "issues": [item.as_mapping() for item in self.issues],
            "warnings": [item.as_mapping() for item in self.warnings],
            "created_by": self.created_by,
            "notes": self.notes,
        }
        if include_intake_hash:
            payload["intake_hash"] = self.intake_hash
        return payload


@dataclass(frozen=True, slots=True)
class ContractPayloadIntakeReport:
    ok: bool
    source_name: str
    contract_name: str
    contract_version: str
    batch_hash: str
    conformance_hash: str
    write_db: bool
    db_executed: bool
    payload_counts: ContractPayloadIntakeCounts
    accepted_counts: ContractPayloadIntakeCounts
    rejected_counts: ContractPayloadIntakeCounts
    planned_daily_bar_count: int
    planned_corporate_action_count: int
    planned_market_session_count: int
    inserted_counts: ContractPayloadIntakeCounts
    skipped_counts: ContractPayloadIntakeCounts
    issues: tuple[ContractPayloadIntakeIssue, ...]
    warnings: tuple[ContractPayloadIntakeIssue, ...]
    created_by: str
    notes: str | None
    intake_hash: str

    def as_mapping(self, *, include_intake_hash: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "kind": INTAKE_REPORT_KIND,
            "format_version": INTAKE_REPORT_FORMAT_VERSION,
            "ok": self.ok,
            "source_name": self.source_name,
            "contract_name": self.contract_name,
            "contract_version": self.contract_version,
            "batch_hash": self.batch_hash,
            "conformance_hash": self.conformance_hash,
            "write_db": self.write_db,
            "db_executed": self.db_executed,
            "payload_counts": self.payload_counts.as_mapping(),
            "accepted_counts": self.accepted_counts.as_mapping(),
            "rejected_counts": self.rejected_counts.as_mapping(),
            "planned_daily_bar_count": self.planned_daily_bar_count,
            "planned_corporate_action_count": self.planned_corporate_action_count,
            "planned_market_session_count": self.planned_market_session_count,
            "inserted_counts": self.inserted_counts.as_mapping(),
            "skipped_counts": self.skipped_counts.as_mapping(),
            "issues": [item.as_mapping() for item in self.issues],
            "warnings": [item.as_mapping() for item in self.warnings],
            "created_by": self.created_by,
            "notes": self.notes,
        }
        if include_intake_hash:
            payload["intake_hash"] = self.intake_hash
        return payload


@dataclass(frozen=True, slots=True)
class ContractPayloadIntakeArtifact:
    name: str
    path: str
    kind: str = "json"

    def as_mapping(self) -> dict[str, object]:
        return {"name": self.name, "path": self.path, "kind": self.kind}


@dataclass(frozen=True, slots=True)
class ContractPayloadIntakeManifest:
    source_name: str
    contract_name: str
    contract_version: str
    batch_hash: str
    conformance_hash: str
    intake_hash: str
    write_db: bool
    db_executed: bool
    ok: bool
    payload_counts: ContractPayloadIntakeCounts
    accepted_counts: ContractPayloadIntakeCounts
    rejected_counts: ContractPayloadIntakeCounts
    inserted_counts: ContractPayloadIntakeCounts
    skipped_counts: ContractPayloadIntakeCounts
    issue_count: int
    artifacts: tuple[ContractPayloadIntakeArtifact, ...]

    def as_mapping(self) -> dict[str, object]:
        return {
            "kind": INTAKE_MANIFEST_KIND,
            "format_version": INTAKE_MANIFEST_FORMAT_VERSION,
            "source_name": self.source_name,
            "contract_name": self.contract_name,
            "contract_version": self.contract_version,
            "batch_hash": self.batch_hash,
            "conformance_hash": self.conformance_hash,
            "intake_hash": self.intake_hash,
            "write_db": self.write_db,
            "db_executed": self.db_executed,
            "ok": self.ok,
            "payload_counts": self.payload_counts.as_mapping(),
            "accepted_counts": self.accepted_counts.as_mapping(),
            "rejected_counts": self.rejected_counts.as_mapping(),
            "inserted_counts": self.inserted_counts.as_mapping(),
            "skipped_counts": self.skipped_counts.as_mapping(),
            "issue_count": self.issue_count,
            "artifacts": [item.as_mapping() for item in self.artifacts],
        }


@dataclass(frozen=True, slots=True)
class ContractPayloadIntakeIntegrityReport:
    ok: bool
    issues: tuple[ContractPayloadIntakeIssue, ...]
    error_count: int

    def as_mapping(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "issues": [item.as_mapping() for item in self.issues],
            "error_count": self.error_count,
        }


def empty_intake_counts() -> ContractPayloadIntakeCounts:
    return ContractPayloadIntakeCounts(
        daily_bars=0,
        corporate_actions=0,
        market_sessions=0,
    )


def default_intake_artifacts(
    *,
    include_source_payload: bool = False,
) -> tuple[ContractPayloadIntakeArtifact, ...]:
    artifacts: tuple[ContractPayloadIntakeArtifact, ...] = (
        ContractPayloadIntakeArtifact(name="plan", path=INTAKE_PLAN_ARTIFACT_NAME),
        ContractPayloadIntakeArtifact(name="report", path=INTAKE_REPORT_ARTIFACT_NAME),
        ContractPayloadIntakeArtifact(
            name="manifest",
            path=INTAKE_MANIFEST_ARTIFACT_NAME,
        ),
    )
    if include_source_payload:
        artifacts = (
            *artifacts,
            ContractPayloadIntakeArtifact(
                name="source_payload_batch",
                path=INTAKE_SOURCE_BATCH_ARTIFACT_NAME,
            ),
        )
    return artifacts
