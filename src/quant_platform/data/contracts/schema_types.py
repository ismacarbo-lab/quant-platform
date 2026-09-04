"""Typed data-contract schema export records. Offline only; not a vendor client."""

from __future__ import annotations

from dataclasses import dataclass

SCHEMA_BUNDLE_KIND = "data_contract_schema_bundle"
SCHEMA_BUNDLE_FORMAT_VERSION = 1
SCHEMA_HASH_KIND = "data_contract_schema_bundle"
SCHEMA_HASH_FORMAT_VERSION = 1
SCHEMA_DEFINITION_HASH_KIND = "data_contract_schema_definition"
SCHEMA_DEFINITION_HASH_FORMAT_VERSION = 1
SCHEMA_MANIFEST_KIND = "data_contract_schema_manifest"
SCHEMA_MANIFEST_FORMAT_VERSION = 1
COMPATIBILITY_REPORT_KIND = "data_contract_schema_compatibility_report"
COMPATIBILITY_REPORT_FORMAT_VERSION = 1
COMPATIBILITY_HASH_KIND = "data_contract_schema_compatibility_report"
COMPATIBILITY_HASH_FORMAT_VERSION = 1

DEFAULT_SCHEMA_VERSION = "1"
COMPATIBILITY_STATUS_COMPATIBLE = "compatible"
COMPATIBILITY_STATUS_POTENTIALLY_BREAKING = "potentially_breaking"

SCHEMA_BUNDLE_ARTIFACT_NAME = "data_contract_schema_bundle.json"
SCHEMA_MANIFEST_ARTIFACT_NAME = "data_contract_schema_manifest.json"

EXPORTED_SCHEMA_NAMES: tuple[str, ...] = (
    "DataContractConformanceManifest",
    "DataContractConformanceReport",
    "DataSourceContract",
    "VendorCorporateActionPayload",
    "VendorDailyBarPayload",
    "VendorMarketSessionPayload",
    "VendorPayloadBatch",
)


@dataclass(frozen=True, slots=True)
class ContractSchemaField:
    name: str
    type_repr: str
    required: bool
    enum_values: tuple[str, ...] = ()

    def as_mapping(self) -> dict[str, object]:
        return {
            "name": self.name,
            "type_repr": self.type_repr,
            "required": self.required,
            "enum_values": list(self.enum_values),
        }


@dataclass(frozen=True, slots=True)
class ContractSchemaDefinition:
    schema_name: str
    schema_version: str
    fields: tuple[ContractSchemaField, ...]
    required_fields: tuple[str, ...]
    enum_values: tuple[tuple[str, tuple[str, ...]], ...]
    hash: str

    def as_mapping(self, *, include_hash: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_name": self.schema_name,
            "schema_version": self.schema_version,
            "fields": [item.as_mapping() for item in self.fields],
            "required_fields": list(self.required_fields),
            "enum_values": {name: list(values) for name, values in self.enum_values},
        }
        if include_hash:
            payload["hash"] = self.hash
        return payload


@dataclass(frozen=True, slots=True)
class ContractSchemaBundle:
    schemas: tuple[ContractSchemaDefinition, ...]
    bundle_hash: str
    kind: str = SCHEMA_BUNDLE_KIND
    format_version: int = SCHEMA_BUNDLE_FORMAT_VERSION

    @property
    def schema_count(self) -> int:
        return len(self.schemas)

    def as_mapping(self, *, include_bundle_hash: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "kind": self.kind,
            "format_version": self.format_version,
            "schema_count": self.schema_count,
            "schemas": [item.as_mapping() for item in self.schemas],
        }
        if include_bundle_hash:
            payload["bundle_hash"] = self.bundle_hash
        return payload


@dataclass(frozen=True, slots=True)
class ContractSchemaCompatibilityIssue:
    code: str
    schema_name: str
    message: str
    field: str | None = None
    previous: str | None = None
    current: str | None = None

    def as_mapping(self) -> dict[str, object]:
        return {
            "code": self.code,
            "schema_name": self.schema_name,
            "field": self.field,
            "message": self.message,
            "previous": self.previous,
            "current": self.current,
        }


@dataclass(frozen=True, slots=True)
class ContractSchemaCompatibilityReport:
    compatibility_status: str
    ok: bool
    issue_count: int
    issues: tuple[ContractSchemaCompatibilityIssue, ...]
    previous_bundle_hash: str
    current_bundle_hash: str
    report_hash: str

    def as_mapping(self, *, include_report_hash: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "kind": COMPATIBILITY_REPORT_KIND,
            "format_version": COMPATIBILITY_REPORT_FORMAT_VERSION,
            "compatibility_status": self.compatibility_status,
            "ok": self.ok,
            "issue_count": self.issue_count,
            "issues": [item.as_mapping() for item in self.issues],
            "previous_bundle_hash": self.previous_bundle_hash,
            "current_bundle_hash": self.current_bundle_hash,
        }
        if include_report_hash:
            payload["report_hash"] = self.report_hash
        return payload


@dataclass(frozen=True, slots=True)
class ContractSchemaArtifact:
    name: str
    path: str
    kind: str = "json"

    def as_mapping(self) -> dict[str, object]:
        return {"name": self.name, "path": self.path, "kind": self.kind}


@dataclass(frozen=True, slots=True)
class ContractSchemaArtifactManifest:
    bundle_hash: str
    schema_count: int
    schema_names: tuple[str, ...]
    artifacts: tuple[ContractSchemaArtifact, ...]

    def as_mapping(self) -> dict[str, object]:
        return {
            "kind": SCHEMA_MANIFEST_KIND,
            "format_version": SCHEMA_MANIFEST_FORMAT_VERSION,
            "bundle_hash": self.bundle_hash,
            "schema_count": self.schema_count,
            "schema_names": list(self.schema_names),
            "artifacts": [item.as_mapping() for item in self.artifacts],
        }


def default_schema_artifacts() -> tuple[ContractSchemaArtifact, ...]:
    return (
        ContractSchemaArtifact(
            name="bundle",
            path=SCHEMA_BUNDLE_ARTIFACT_NAME,
        ),
        ContractSchemaArtifact(
            name="manifest",
            path=SCHEMA_MANIFEST_ARTIFACT_NAME,
        ),
    )
