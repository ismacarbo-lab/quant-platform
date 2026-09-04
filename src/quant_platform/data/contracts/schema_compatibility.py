"""Offline schema compatibility checks. Simple rules; not semver or vendors."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

from quant_platform.data.contracts.errors import (
    VendorContractError,
    VendorContractErrorCode,
)
from quant_platform.data.contracts.hashing import sha256_canonical_mapping
from quant_platform.data.contracts.schema_export import (
    build_contract_schema_bundle,
    default_expected_compatibility_path,
    default_schema_baseline_path,
    load_contract_schema_bundle,
)
from quant_platform.data.contracts.schema_types import (
    COMPATIBILITY_HASH_FORMAT_VERSION,
    COMPATIBILITY_HASH_KIND,
    COMPATIBILITY_STATUS_COMPATIBLE,
    COMPATIBILITY_STATUS_POTENTIALLY_BREAKING,
    ContractSchemaBundle,
    ContractSchemaCompatibilityIssue,
    ContractSchemaCompatibilityReport,
    ContractSchemaDefinition,
    ContractSchemaField,
)


def compare_contract_schema_bundles(
    previous: ContractSchemaBundle,
    current: ContractSchemaBundle,
) -> tuple[ContractSchemaCompatibilityIssue, ...]:
    """Diff two schema bundles. Compatible additions do not emit issues."""
    issues: list[ContractSchemaCompatibilityIssue] = []
    previous_by_name = {item.schema_name: item for item in previous.schemas}
    current_by_name = {item.schema_name: item for item in current.schemas}
    for schema_name, previous_schema in previous_by_name.items():
        current_schema = current_by_name.get(schema_name)
        if current_schema is None:
            issues.append(
                ContractSchemaCompatibilityIssue(
                    code="schema_removed",
                    schema_name=schema_name,
                    message=f"schema {schema_name} was removed",
                    previous=schema_name,
                )
            )
            continue
        issues.extend(_compare_definitions(previous_schema, current_schema))
    issues.sort(key=lambda item: (item.code, item.schema_name, item.field or ""))
    return tuple(issues)


def evaluate_schema_compatibility(
    previous: ContractSchemaBundle,
    current: ContractSchemaBundle,
) -> ContractSchemaCompatibilityReport:
    """Build a hashed compatibility report. No wall-clock or absolute paths."""
    issues = compare_contract_schema_bundles(previous, current)
    status = (
        COMPATIBILITY_STATUS_COMPATIBLE
        if not issues
        else COMPATIBILITY_STATUS_POTENTIALLY_BREAKING
    )
    draft = ContractSchemaCompatibilityReport(
        compatibility_status=status,
        ok=not issues,
        issue_count=len(issues),
        issues=issues,
        previous_bundle_hash=previous.bundle_hash,
        current_bundle_hash=current.bundle_hash,
        report_hash="",
    )
    return replace(draft, report_hash=hash_schema_compatibility_report(draft))


def hash_schema_compatibility_report(
    report: ContractSchemaCompatibilityReport,
) -> str:
    """SHA-256 of the compatibility report body."""
    payload = {
        "kind": COMPATIBILITY_HASH_KIND,
        "version": COMPATIBILITY_HASH_FORMAT_VERSION,
        "compatibility_status": report.compatibility_status,
        "ok": report.ok,
        "issue_count": report.issue_count,
        "issues": [item.as_mapping() for item in report.issues],
        "previous_bundle_hash": report.previous_bundle_hash,
        "current_bundle_hash": report.current_bundle_hash,
    }
    return sha256_canonical_mapping(payload)


def check_schema_compatibility_against_baseline(
    *,
    baseline_file: Path | str | None = None,
    current: ContractSchemaBundle | None = None,
) -> ContractSchemaCompatibilityReport:
    """Compare the live export against the pinned baseline fixture."""
    previous = load_contract_schema_bundle(
        default_schema_baseline_path() if baseline_file is None else baseline_file
    )
    live = current if current is not None else build_contract_schema_bundle()
    return evaluate_schema_compatibility(previous, live)


def load_expected_compatibility(
    path: Path | str | None = None,
) -> dict[str, object]:
    """Load the current-vs-current expected compatibility fixture."""
    target = default_expected_compatibility_path() if path is None else Path(path)
    try:
        raw = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise VendorContractError(
            "expected compatibility fixture could not be read",
            code=VendorContractErrorCode.FIXTURE_UNREADABLE,
        ) from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise VendorContractError(
            "expected compatibility fixture is not valid JSON",
            code=VendorContractErrorCode.FIXTURE_UNREADABLE,
        ) from exc
    if not isinstance(payload, dict):
        raise VendorContractError(
            "expected compatibility fixture must be a JSON object",
            code=VendorContractErrorCode.FIXTURE_UNREADABLE,
        )
    return payload


def _compare_definitions(
    previous: ContractSchemaDefinition,
    current: ContractSchemaDefinition,
) -> list[ContractSchemaCompatibilityIssue]:
    issues: list[ContractSchemaCompatibilityIssue] = []
    previous_major = _major_version(previous.schema_version)
    current_major = _major_version(current.schema_version)
    if previous_major != current_major:
        issues.append(
            ContractSchemaCompatibilityIssue(
                code="schema_major_version_changed",
                schema_name=previous.schema_name,
                message=("schema major version changed without a dedicated ADR"),
                previous=previous.schema_version,
                current=current.schema_version,
            )
        )
    previous_fields = {item.name: item for item in previous.fields}
    current_fields = {item.name: item for item in current.fields}
    for name, previous_field in previous_fields.items():
        current_field = current_fields.get(name)
        if current_field is None:
            issues.append(
                ContractSchemaCompatibilityIssue(
                    code="field_removed",
                    schema_name=previous.schema_name,
                    field=name,
                    message=f"field {name} was removed",
                    previous=previous_field.type_repr,
                )
            )
            continue
        issues.extend(
            _compare_fields(
                previous.schema_name,
                previous_field,
                current_field,
            )
        )
    for name, current_field in current_fields.items():
        if name in previous_fields:
            continue
        if current_field.required:
            issues.append(
                ContractSchemaCompatibilityIssue(
                    code="field_added_required",
                    schema_name=previous.schema_name,
                    field=name,
                    message=f"required field {name} was added",
                    current=current_field.type_repr,
                )
            )
    return issues


def _compare_fields(
    schema_name: str,
    previous: ContractSchemaField,
    current: ContractSchemaField,
) -> list[ContractSchemaCompatibilityIssue]:
    issues: list[ContractSchemaCompatibilityIssue] = []
    if previous.type_repr != current.type_repr:
        issues.append(
            ContractSchemaCompatibilityIssue(
                code="type_changed",
                schema_name=schema_name,
                field=previous.name,
                message=f"field {previous.name} changed type",
                previous=previous.type_repr,
                current=current.type_repr,
            )
        )
    if not previous.required and current.required:
        issues.append(
            ContractSchemaCompatibilityIssue(
                code="field_became_required",
                schema_name=schema_name,
                field=previous.name,
                message=f"field {previous.name} became required",
                previous="optional",
                current="required",
            )
        )
    removed_enums = tuple(sorted(set(previous.enum_values) - set(current.enum_values)))
    if removed_enums:
        issues.append(
            ContractSchemaCompatibilityIssue(
                code="enum_removed",
                schema_name=schema_name,
                field=previous.name,
                message=(
                    f"enum values removed from {previous.name}: "
                    + ", ".join(removed_enums)
                ),
                previous=",".join(removed_enums),
            )
        )
    return issues


def _major_version(version: str) -> int:
    head = version.strip().split(".", 1)[0]
    try:
        return int(head)
    except ValueError:
        return 0


def expected_compatibility_matches(
    report: ContractSchemaCompatibilityReport,
    expected: Mapping[str, object],
) -> bool:
    status = expected.get("compatibility_status")
    issue_count = expected.get("issue_count")
    codes = expected.get("expected_issue_codes", [])
    if status != report.compatibility_status:
        return False
    if issue_count != report.issue_count:
        return False
    if not isinstance(codes, list):
        return False
    actual_codes = [item.code for item in report.issues]
    return actual_codes == [str(item) for item in codes]
