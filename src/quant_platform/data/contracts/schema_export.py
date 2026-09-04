"""Deterministic JSON schema export for vendor-agnostic contracts. Offline only."""

from __future__ import annotations

import json
import types
from collections.abc import Mapping
from dataclasses import MISSING, fields, replace
from enum import Enum
from pathlib import Path
from typing import Union, get_args, get_origin, get_type_hints

from quant_platform.data.contracts.conformance_types import (
    DataContractConformanceManifest,
    DataContractConformanceReport,
)
from quant_platform.data.contracts.errors import (
    VendorContractError,
    VendorContractErrorCode,
)
from quant_platform.data.contracts.hashing import (
    jsonable_vendor_payload,
    sha256_canonical_mapping,
)
from quant_platform.data.contracts.schema_types import (
    DEFAULT_SCHEMA_VERSION,
    EXPORTED_SCHEMA_NAMES,
    SCHEMA_BUNDLE_ARTIFACT_NAME,
    SCHEMA_BUNDLE_FORMAT_VERSION,
    SCHEMA_BUNDLE_KIND,
    SCHEMA_DEFINITION_HASH_FORMAT_VERSION,
    SCHEMA_DEFINITION_HASH_KIND,
    SCHEMA_HASH_FORMAT_VERSION,
    SCHEMA_HASH_KIND,
    SCHEMA_MANIFEST_ARTIFACT_NAME,
    ContractSchemaArtifactManifest,
    ContractSchemaBundle,
    ContractSchemaDefinition,
    ContractSchemaField,
    default_schema_artifacts,
)
from quant_platform.data.contracts.types import (
    ALLOWED_ACTION_TYPES,
    ALLOWED_SESSION_KINDS,
    ALLOWED_SOURCE_KINDS,
    DataSourceContract,
    DataVendorCapability,
    VendorCorporateActionPayload,
    VendorDailyBarPayload,
    VendorMarketSessionPayload,
    VendorPayloadBatch,
)
from quant_platform.simulation.run_types import artifact_path_is_unsafe

_SECRET_MARKERS = (
    "DATABASE_URL",
    "POSTGRES_PASSWORD",
    "postgresql://",
    "postgres://",
    "postgresql+psycopg://",
)

_EXPORTED_CLASSES: tuple[type, ...] = (
    DataContractConformanceManifest,
    DataContractConformanceReport,
    DataSourceContract,
    VendorCorporateActionPayload,
    VendorDailyBarPayload,
    VendorMarketSessionPayload,
    VendorPayloadBatch,
)

_FIELD_ENUMS: dict[tuple[str, str], tuple[str, ...]] = {
    ("DataSourceContract", "source_kind"): tuple(sorted(ALLOWED_SOURCE_KINDS)),
    ("DataSourceContract", "capabilities"): tuple(
        sorted(item.value for item in DataVendorCapability)
    ),
    ("VendorCorporateActionPayload", "action_type"): tuple(
        sorted(ALLOWED_ACTION_TYPES)
    ),
    ("VendorMarketSessionPayload", "session_kind"): tuple(
        sorted(ALLOWED_SESSION_KINDS)
    ),
}


def build_contract_schema_bundle() -> ContractSchemaBundle:
    """Introspect local dataclasses into a deterministic schema bundle."""
    schemas = tuple(
        _schema_definition_for(cls)
        for cls in sorted(_EXPORTED_CLASSES, key=lambda item: item.__name__)
    )
    names = tuple(item.schema_name for item in schemas)
    if names != EXPORTED_SCHEMA_NAMES:
        raise VendorContractError(
            "exported schema names do not match the pinned inventory",
            code=VendorContractErrorCode.VALIDATION_ERROR,
        )
    draft = ContractSchemaBundle(schemas=schemas, bundle_hash="")
    return replace(draft, bundle_hash=hash_contract_schema_bundle(draft))


def hash_schema_definition(definition: ContractSchemaDefinition) -> str:
    """SHA-256 of one schema definition. Omits the stored hash field."""
    payload = {
        "kind": SCHEMA_DEFINITION_HASH_KIND,
        "version": SCHEMA_DEFINITION_HASH_FORMAT_VERSION,
        "schema_name": definition.schema_name,
        "schema_version": definition.schema_version,
        "fields": [item.as_mapping() for item in definition.fields],
        "required_fields": list(definition.required_fields),
        "enum_values": {name: list(values) for name, values in definition.enum_values},
    }
    return sha256_canonical_mapping(payload)


def hash_contract_schema_bundle(bundle: ContractSchemaBundle) -> str:
    """SHA-256 of the schema bundle. Same contract definitions → same digest."""
    payload = {
        "kind": SCHEMA_HASH_KIND,
        "version": SCHEMA_HASH_FORMAT_VERSION,
        "format_version": SCHEMA_BUNDLE_FORMAT_VERSION,
        "schemas": [
            {
                "schema_name": item.schema_name,
                "schema_version": item.schema_version,
                "hash": item.hash,
                "fields": [field.as_mapping() for field in item.fields],
                "required_fields": list(item.required_fields),
                "enum_values": {
                    name: list(values) for name, values in item.enum_values
                },
            }
            for item in bundle.schemas
        ],
    }
    return sha256_canonical_mapping(payload)


def write_contract_schema_bundle(
    output_dir: Path | str,
    *,
    bundle: ContractSchemaBundle | None = None,
) -> ContractSchemaArtifactManifest:
    """Write relative-path schema JSON artifacts. No PostgreSQL, no network."""
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    current = bundle if bundle is not None else build_contract_schema_bundle()
    artifacts = default_schema_artifacts()
    for item in artifacts:
        if artifact_path_is_unsafe(item.path):
            raise VendorContractError(
                "schema artifact paths must be relative",
                code=VendorContractErrorCode.VALIDATION_ERROR,
            )
    _write_json(current.as_mapping(), root / SCHEMA_BUNDLE_ARTIFACT_NAME)
    manifest = ContractSchemaArtifactManifest(
        bundle_hash=current.bundle_hash,
        schema_count=current.schema_count,
        schema_names=tuple(item.schema_name for item in current.schemas),
        artifacts=artifacts,
    )
    _write_json(manifest.as_mapping(), root / SCHEMA_MANIFEST_ARTIFACT_NAME)
    return manifest


def default_data_contract_schema_dir() -> Path:
    """Resolve ``tests/fixtures/data_contract_schemas`` from the repository."""
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "tests" / "fixtures" / "data_contract_schemas"
        if candidate.is_dir():
            return candidate
    raise VendorContractError(
        "data-contract schema fixtures directory is missing",
        code=VendorContractErrorCode.FIXTURE_UNREADABLE,
    )


def default_schema_baseline_path() -> Path:
    """Pinned current schema baseline JSON. Copied by hand after review."""
    return default_data_contract_schema_dir() / "current_baseline.json"


def default_expected_compatibility_path() -> Path:
    return default_data_contract_schema_dir() / "expected_compatibility.json"


def load_contract_schema_bundle(path: Path | str) -> ContractSchemaBundle:
    """Load a schema bundle fixture. Recomputes hashes and checks the digest."""
    target = Path(path)
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except OSError as exc:
        raise VendorContractError(
            "schema baseline could not be read",
            code=VendorContractErrorCode.FIXTURE_UNREADABLE,
        ) from exc
    except json.JSONDecodeError as exc:
        raise VendorContractError(
            "schema baseline is not valid JSON",
            code=VendorContractErrorCode.FIXTURE_UNREADABLE,
        ) from exc
    if not isinstance(raw, dict):
        raise VendorContractError(
            "schema baseline must be a JSON object",
            code=VendorContractErrorCode.FIXTURE_UNREADABLE,
        )
    return contract_schema_bundle_from_mapping(raw)


def contract_schema_bundle_from_mapping(
    payload: Mapping[str, object],
) -> ContractSchemaBundle:
    """Rebuild a bundle from canonical JSON. Rejects hash drift."""
    kind = payload.get("kind")
    if kind != SCHEMA_BUNDLE_KIND:
        raise VendorContractError(
            "schema bundle kind is invalid",
            code=VendorContractErrorCode.VALIDATION_ERROR,
        )
    format_version = payload.get("format_version")
    if format_version != SCHEMA_BUNDLE_FORMAT_VERSION:
        raise VendorContractError(
            "schema bundle format_version is invalid",
            code=VendorContractErrorCode.VALIDATION_ERROR,
        )
    raw_schemas = payload.get("schemas")
    if not isinstance(raw_schemas, list):
        raise VendorContractError(
            "schema bundle schemas must be a list",
            code=VendorContractErrorCode.VALIDATION_ERROR,
        )
    schemas = tuple(_definition_from_mapping(item) for item in raw_schemas)
    draft = ContractSchemaBundle(
        kind=SCHEMA_BUNDLE_KIND,
        format_version=SCHEMA_BUNDLE_FORMAT_VERSION,
        schemas=schemas,
        bundle_hash="",
    )
    recomputed = hash_contract_schema_bundle(draft)
    stored = payload.get("bundle_hash")
    if not isinstance(stored, str) or stored != recomputed:
        raise VendorContractError(
            "schema bundle hash does not match the definitions",
            code=VendorContractErrorCode.VALIDATION_ERROR,
        )
    return replace(draft, bundle_hash=recomputed)


def rebuild_schema_definition(
    definition: ContractSchemaDefinition,
) -> ContractSchemaDefinition:
    """Recompute a definition hash after a test mutation."""
    draft = replace(definition, hash="")
    return replace(draft, hash=hash_schema_definition(draft))


def rebuild_schema_bundle(bundle: ContractSchemaBundle) -> ContractSchemaBundle:
    """Recompute definition and bundle hashes after a test mutation."""
    schemas = tuple(rebuild_schema_definition(item) for item in bundle.schemas)
    draft = replace(bundle, schemas=schemas, bundle_hash="")
    return replace(draft, bundle_hash=hash_contract_schema_bundle(draft))


def _schema_definition_for(cls: type) -> ContractSchemaDefinition:
    hints = get_type_hints(cls)
    schema_fields: list[ContractSchemaField] = []
    required_fields: list[str] = []
    enum_pairs: list[tuple[str, tuple[str, ...]]] = []
    for item in fields(cls):
        annotation = hints.get(item.name, item.type)
        required = item.default is MISSING and item.default_factory is MISSING
        enum_values = _enum_values_for(cls.__name__, item.name, annotation)
        schema_fields.append(
            ContractSchemaField(
                name=item.name,
                type_repr=_type_repr(annotation),
                required=required,
                enum_values=enum_values,
            )
        )
        if required:
            required_fields.append(item.name)
        if enum_values:
            enum_pairs.append((item.name, enum_values))
    draft = ContractSchemaDefinition(
        schema_name=cls.__name__,
        schema_version=DEFAULT_SCHEMA_VERSION,
        fields=tuple(schema_fields),
        required_fields=tuple(required_fields),
        enum_values=tuple(enum_pairs),
        hash="",
    )
    return replace(draft, hash=hash_schema_definition(draft))


def _enum_values_for(
    schema_name: str,
    field_name: str,
    annotation: object,
) -> tuple[str, ...]:
    overlay = _FIELD_ENUMS.get((schema_name, field_name))
    if overlay is not None:
        return overlay
    values = _enum_values_from_annotation(annotation)
    return tuple(sorted(values))


def _enum_values_from_annotation(annotation: object) -> tuple[str, ...]:
    collected: set[str] = set()
    for candidate in _annotation_types(annotation):
        if isinstance(candidate, type) and issubclass(candidate, Enum):
            for member in candidate:
                collected.add(str(member.value))
    return tuple(sorted(collected))


def _annotation_types(annotation: object) -> tuple[object, ...]:
    origin = get_origin(annotation)
    args = get_args(annotation)
    found: list[object] = [annotation]
    if args:
        found.extend(args)
        for arg in args:
            nested = get_args(arg)
            if nested:
                found.extend(nested)
    if origin is not None:
        found.append(origin)
    return tuple(found)


def _type_repr(annotation: object) -> str:
    if annotation is type(None):
        return "None"
    if annotation is Ellipsis:
        return "..."
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is Union or origin is types.UnionType:
        parts = [_type_repr(arg) for arg in args]
        non_none = [part for part in parts if part != "None"]
        none_part = ["None"] if "None" in parts else []
        return " | ".join(non_none + none_part)
    if origin is tuple:
        inner = ", ".join(_type_repr(arg) for arg in args)
        return f"tuple[{inner}]"
    if origin is list:
        if not args:
            return "list"
        return f"list[{_type_repr(args[0])}]"
    if origin is dict or origin is Mapping:
        if len(args) == 2:
            return f"Mapping[{_type_repr(args[0])}, {_type_repr(args[1])}]"
        return "Mapping"
    if isinstance(annotation, type):
        return annotation.__name__
    if isinstance(annotation, str):
        return annotation
    return str(annotation).replace("typing.", "")


def _definition_from_mapping(raw: object) -> ContractSchemaDefinition:
    if not isinstance(raw, dict):
        raise VendorContractError(
            "schema definition must be a JSON object",
            code=VendorContractErrorCode.VALIDATION_ERROR,
        )
    schema_name = raw.get("schema_name")
    schema_version = raw.get("schema_version")
    if not isinstance(schema_name, str) or not schema_name:
        raise VendorContractError(
            "schema_name is required",
            code=VendorContractErrorCode.VALIDATION_ERROR,
        )
    if not isinstance(schema_version, str) or not schema_version:
        raise VendorContractError(
            "schema_version is required",
            code=VendorContractErrorCode.VALIDATION_ERROR,
        )
    raw_fields = raw.get("fields")
    if not isinstance(raw_fields, list):
        raise VendorContractError(
            "schema fields must be a list",
            code=VendorContractErrorCode.VALIDATION_ERROR,
        )
    parsed_fields = tuple(_field_from_mapping(item) for item in raw_fields)
    raw_required = raw.get("required_fields")
    if not isinstance(raw_required, list):
        raise VendorContractError(
            "required_fields must be a list",
            code=VendorContractErrorCode.VALIDATION_ERROR,
        )
    required_fields = tuple(str(item) for item in raw_required)
    enum_values = _enum_pairs_from_mapping(raw.get("enum_values"))
    draft = ContractSchemaDefinition(
        schema_name=schema_name,
        schema_version=schema_version,
        fields=parsed_fields,
        required_fields=required_fields,
        enum_values=enum_values,
        hash="",
    )
    recomputed = hash_schema_definition(draft)
    stored = raw.get("hash")
    if not isinstance(stored, str) or stored != recomputed:
        raise VendorContractError(
            f"schema hash mismatch for {schema_name}",
            code=VendorContractErrorCode.VALIDATION_ERROR,
        )
    return replace(draft, hash=recomputed)


def _field_from_mapping(raw: object) -> ContractSchemaField:
    if not isinstance(raw, dict):
        raise VendorContractError(
            "schema field must be a JSON object",
            code=VendorContractErrorCode.VALIDATION_ERROR,
        )
    name = raw.get("name")
    type_repr = raw.get("type_repr")
    required = raw.get("required")
    if not isinstance(name, str) or not name:
        raise VendorContractError(
            "schema field name is required",
            code=VendorContractErrorCode.VALIDATION_ERROR,
        )
    if not isinstance(type_repr, str) or not type_repr:
        raise VendorContractError(
            "schema field type_repr is required",
            code=VendorContractErrorCode.VALIDATION_ERROR,
        )
    if not isinstance(required, bool):
        raise VendorContractError(
            "schema field required must be a boolean",
            code=VendorContractErrorCode.VALIDATION_ERROR,
        )
    raw_enums = raw.get("enum_values", [])
    if not isinstance(raw_enums, list):
        raise VendorContractError(
            "schema field enum_values must be a list",
            code=VendorContractErrorCode.VALIDATION_ERROR,
        )
    return ContractSchemaField(
        name=name,
        type_repr=type_repr,
        required=required,
        enum_values=tuple(str(item) for item in raw_enums),
    )


def _enum_pairs_from_mapping(
    raw: object,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if raw is None:
        return ()
    if not isinstance(raw, dict):
        raise VendorContractError(
            "schema enum_values must be an object",
            code=VendorContractErrorCode.VALIDATION_ERROR,
        )
    pairs: list[tuple[str, tuple[str, ...]]] = []
    for key, values in raw.items():
        if not isinstance(values, list):
            raise VendorContractError(
                "schema enum_values entries must be lists",
                code=VendorContractErrorCode.VALIDATION_ERROR,
            )
        pairs.append((str(key), tuple(str(item) for item in values)))
    return tuple(pairs)


def _write_json(payload: Mapping[str, object], path: Path) -> None:
    if artifact_path_is_unsafe(path.name):
        raise VendorContractError(
            "schema artifact paths must be relative",
            code=VendorContractErrorCode.VALIDATION_ERROR,
        )
    converted = jsonable_vendor_payload(dict(payload))
    if not isinstance(converted, dict):
        raise VendorContractError(
            "schema artifact JSON must be an object",
            code=VendorContractErrorCode.VALIDATION_ERROR,
        )
    text = json.dumps(converted, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    lowered = text.lower()
    for marker in _SECRET_MARKERS:
        if marker.lower() in lowered:
            raise VendorContractError(
                "schema artifacts must not contain secrets",
                code=VendorContractErrorCode.SECRET_IN_METADATA,
            )
    path.write_text(text, encoding="utf-8")
