"""Offline data-contract schema export and compatibility. No vendors or trading."""

from __future__ import annotations

import ast
import importlib.util
import json
import re
from dataclasses import replace
from pathlib import Path

import pytest

from quant_platform.core.config import Settings
from quant_platform.data.contracts.schema_compatibility import (
    check_schema_compatibility_against_baseline,
    compare_contract_schema_bundles,
    evaluate_schema_compatibility,
    expected_compatibility_matches,
    hash_schema_compatibility_report,
    load_expected_compatibility,
)
from quant_platform.data.contracts.schema_export import (
    build_contract_schema_bundle,
    default_data_contract_schema_dir,
    default_expected_compatibility_path,
    default_schema_baseline_path,
    hash_contract_schema_bundle,
    hash_schema_definition,
    load_contract_schema_bundle,
    rebuild_schema_bundle,
    write_contract_schema_bundle,
)
from quant_platform.data.contracts.schema_types import (
    EXPORTED_SCHEMA_NAMES,
    ContractSchemaField,
)
from quant_platform.release.constants import DISABLED_CAPABILITIES, ENABLED_CAPABILITIES
from quant_platform.release.guards import (
    detect_contracts_networking,
    detect_real_vendor_clients,
)
from quant_platform.simulation.constructs import detect_trading_constructs
from quant_platform.simulation.run_types import artifact_path_is_unsafe

_ROOT = Path(__file__).resolve().parents[2]
_PACKAGE = _ROOT / "src" / "quant_platform"
_SCRIPTS = _ROOT / "scripts"
_CONTRACTS = _PACKAGE / "data" / "contracts"
_SCHEMA_FILES = (
    _CONTRACTS / "schema_types.py",
    _CONTRACTS / "schema_export.py",
    _CONTRACTS / "schema_compatibility.py",
)
_NETWORK_MODULES = {"requests", "httpx", "aiohttp", "urllib", "socket"}
_FORBIDDEN_JSON_TERMS = re.compile(
    r"(?i)\b(?:pnl|sharpe|drawdown|hit_ratio|exposure|portfolio_value)\b"
)
_VENDOR_FILENAMES = {
    "polygon.py",
    "yfinance.py",
    "alpaca.py",
    "binance.py",
    "yahoo.py",
    "tiingo.py",
    "iex.py",
    "bloomberg.py",
    "refinitiv.py",
    "nasdaq.py",
    "coinbase.py",
}


def _load_script(filename: str):
    path = _SCRIPTS / filename
    spec = importlib.util.spec_from_file_location(filename.replace("-", "_"), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _mutate_field(
    bundle,
    schema_name: str,
    field_name: str,
    **changes: object,
):
    schemas = []
    for schema in bundle.schemas:
        if schema.schema_name != schema_name:
            schemas.append(schema)
            continue
        fields = []
        for item in schema.fields:
            if item.name == field_name:
                fields.append(replace(item, **changes))
            else:
                fields.append(item)
        required = tuple(item.name for item in fields if item.required)
        enum_values = tuple(
            (item.name, item.enum_values) for item in fields if item.enum_values
        )
        schemas.append(
            replace(
                schema,
                fields=tuple(fields),
                required_fields=required,
                enum_values=enum_values,
                hash="",
            )
        )
    return rebuild_schema_bundle(
        replace(bundle, schemas=tuple(schemas), bundle_hash="")
    )


def _drop_field(bundle, schema_name: str, field_name: str):
    schemas = []
    for schema in bundle.schemas:
        if schema.schema_name != schema_name:
            schemas.append(schema)
            continue
        fields = tuple(item for item in schema.fields if item.name != field_name)
        schemas.append(
            replace(
                schema,
                fields=fields,
                required_fields=tuple(item.name for item in fields if item.required),
                enum_values=tuple(
                    (item.name, item.enum_values) for item in fields if item.enum_values
                ),
                hash="",
            )
        )
    return rebuild_schema_bundle(
        replace(bundle, schemas=tuple(schemas), bundle_hash="")
    )


def test_schema_bundle_exports_expected_schemas() -> None:
    bundle = build_contract_schema_bundle()
    names = tuple(item.schema_name for item in bundle.schemas)
    assert names == EXPORTED_SCHEMA_NAMES
    assert bundle.schema_count == len(EXPORTED_SCHEMA_NAMES)
    for schema in bundle.schemas:
        assert schema.schema_version == "1"
        assert schema.fields
        assert schema.hash.startswith("sha256:")
        assert schema.hash == hash_schema_definition(schema)
        names_in_fields = [item.name for item in schema.fields]
        assert schema.required_fields == tuple(
            item.name for item in schema.fields if item.required
        )
        assert len(set(names_in_fields)) == len(names_in_fields)


def test_schema_hash_is_stable() -> None:
    first = build_contract_schema_bundle()
    second = build_contract_schema_bundle()
    assert first.bundle_hash == second.bundle_hash
    assert first.bundle_hash == hash_contract_schema_bundle(first)
    assert first.bundle_hash == hash_contract_schema_bundle(second)
    blob = json.dumps(first.as_mapping(), sort_keys=True)
    assert "DATABASE_URL" not in blob
    assert "postgresql+psycopg://" not in blob


def test_schema_hash_changes_when_definition_changes() -> None:
    original = build_contract_schema_bundle()
    changed = _mutate_field(
        original,
        "DataSourceContract",
        "source_name",
        type_repr="int",
    )
    assert changed.bundle_hash != original.bundle_hash


def test_baseline_current_versus_current_is_compatible() -> None:
    bundle = build_contract_schema_bundle()
    baseline = load_contract_schema_bundle(default_schema_baseline_path())
    assert baseline.bundle_hash == bundle.bundle_hash
    report = evaluate_schema_compatibility(baseline, bundle)
    assert report.compatibility_status == "compatible"
    assert report.ok is True
    assert report.issue_count == 0
    assert report.issues == ()
    assert report.report_hash == hash_schema_compatibility_report(report)
    expected = load_expected_compatibility()
    assert expected_compatibility_matches(report, expected)
    pinned = check_schema_compatibility_against_baseline()
    assert pinned.ok is True


def test_removed_field_is_potentially_breaking() -> None:
    original = build_contract_schema_bundle()
    current = _drop_field(original, "VendorDailyBarPayload", "symbol")
    report = evaluate_schema_compatibility(original, current)
    assert report.ok is False
    assert report.compatibility_status == "potentially_breaking"
    codes = {item.code for item in report.issues}
    assert "field_removed" in codes


def test_type_change_is_potentially_breaking() -> None:
    original = build_contract_schema_bundle()
    current = _mutate_field(
        original,
        "VendorDailyBarPayload",
        "open",
        type_repr="str",
    )
    report = evaluate_schema_compatibility(original, current)
    assert report.ok is False
    codes = [item.code for item in report.issues]
    assert "type_changed" in codes


def test_required_field_change_is_potentially_breaking() -> None:
    original = build_contract_schema_bundle()
    current = _mutate_field(
        original,
        "DataSourceContract",
        "capture_raw_payload",
        required=True,
    )
    report = evaluate_schema_compatibility(original, current)
    assert report.ok is False
    codes = [item.code for item in report.issues]
    assert "field_became_required" in codes


def test_enum_removal_is_potentially_breaking() -> None:
    original = build_contract_schema_bundle()
    current = _mutate_field(
        original,
        "VendorCorporateActionPayload",
        "action_type",
        enum_values=("split", "reverse_split", "dividend", "symbol_change"),
    )
    report = evaluate_schema_compatibility(original, current)
    assert report.ok is False
    codes = [item.code for item in report.issues]
    assert "enum_removed" in codes


def test_optional_field_addition_is_compatible() -> None:
    original = build_contract_schema_bundle()
    extra = ContractSchemaField(
        name="future_note",
        type_repr="str | None",
        required=False,
        enum_values=(),
    )
    schemas = []
    for schema in original.schemas:
        if schema.schema_name != "DataSourceContract":
            schemas.append(schema)
            continue
        schemas.append(
            replace(
                schema,
                fields=(*schema.fields, extra),
                hash="",
            )
        )
    current = rebuild_schema_bundle(
        replace(original, schemas=tuple(schemas), bundle_hash="")
    )
    issues = compare_contract_schema_bundles(original, current)
    report = evaluate_schema_compatibility(original, current)
    assert issues == ()
    assert report.ok is True
    assert report.compatibility_status == "compatible"


def test_schema_artifacts_use_relative_paths(tmp_path: Path) -> None:
    bundle = build_contract_schema_bundle()
    manifest = write_contract_schema_bundle(tmp_path, bundle=bundle)
    blob = json.dumps(manifest.as_mapping(), sort_keys=True)
    assert "DATABASE_URL" not in blob
    assert str(tmp_path) not in blob
    for item in manifest.artifacts:
        assert not Path(item.path).is_absolute()
        assert artifact_path_is_unsafe(item.path) is False
        assert (tmp_path / item.path).is_file()
    loaded = load_contract_schema_bundle(tmp_path / "data_contract_schema_bundle.json")
    assert loaded.bundle_hash == bundle.bundle_hash


def test_export_and_compatibility_scripts_json(
    monkeypatch: pytest.MonkeyPatch,
    research_settings: Settings,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exporter = _load_script("export-data-contract-schemas.py")
    checker = _load_script("check-data-contract-schema-compatibility.py")
    monkeypatch.setattr(exporter, "get_settings", lambda: research_settings)
    monkeypatch.setattr(checker, "get_settings", lambda: research_settings)
    export_code = exporter.main(["--json", "--output-dir", str(tmp_path / "out")])
    export_out = capsys.readouterr()
    assert export_code == 0
    exported = json.loads(export_out.out)
    assert exported["kind"] == "data_contract_schema_bundle"
    assert "DATABASE_URL" not in export_out.out
    check_code = checker.main(["--json"])
    check_out = capsys.readouterr()
    assert check_code == 0
    report = json.loads(check_out.out)
    assert report["kind"] == "data_contract_schema_compatibility_report"
    assert report["compatibility_status"] == "compatible"
    assert report["issue_count"] == 0
    assert "DATABASE_URL" not in check_out.out
    write_code = checker.main(["--json", "--write-current", str(tmp_path / "current")])
    write_out = capsys.readouterr()
    assert write_code == 0
    written = json.loads(write_out.out)
    assert written["ok"] is True
    assert (tmp_path / "current" / "data_contract_schema_bundle.json").is_file()


def test_no_real_vendors_or_network_imports() -> None:
    assert detect_contracts_networking(_PACKAGE) == ()
    assert detect_real_vendor_clients(_PACKAGE) == ()
    enabled = set(ENABLED_CAPABILITIES)
    disabled = set(DISABLED_CAPABILITIES)
    assert "data_contract_schema_baseline" in enabled
    assert "vendor_agnostic_data_contracts" in enabled
    assert "external_market_data_vendors" in disabled
    present = {path.name for path in _CONTRACTS.glob("*.py")}
    assert present.isdisjoint(_VENDOR_FILENAMES)
    findings = detect_trading_constructs(package_root=_PACKAGE)
    assert findings == ()
    for path in _SCHEMA_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        assert imported.isdisjoint(_NETWORK_MODULES)


def test_exported_json_has_no_trading_or_performance_terms() -> None:
    bundle = build_contract_schema_bundle()
    blob = json.dumps(bundle.as_mapping(), sort_keys=True)
    assert _FORBIDDEN_JSON_TERMS.search(blob) is None
    baseline = default_schema_baseline_path().read_text(encoding="utf-8")
    expected = default_expected_compatibility_path().read_text(encoding="utf-8")
    assert _FORBIDDEN_JSON_TERMS.search(baseline) is None
    assert _FORBIDDEN_JSON_TERMS.search(expected) is None
    assert "DATABASE_URL" not in baseline
    assert "DATABASE_URL" not in expected
    assert default_data_contract_schema_dir().name == "data_contract_schemas"


def test_schema_compatibility_docs_exist_without_database_url() -> None:
    spec = _ROOT / "docs" / "data" / "DATA_CONTRACT_SCHEMA_COMPATIBILITY.md"
    assert spec.is_file()
    text = spec.read_text(encoding="utf-8")
    assert "DATABASE_URL" not in text
    assert "postgresql+psycopg://" not in text.lower()
    lowered = text.lower()
    assert "offline" in lowered
    assert "not a trading" in lowered or "not trading" in lowered
    assert "pnl" in lowered
    assert "returns" in lowered
    assert "vendor" in lowered


def test_schema_remote_verification_doc() -> None:
    spec = (
        _ROOT
        / "docs"
        / "release"
        / "DATA_CONTRACT_SCHEMA_REMOTE_RELEASE_VERIFICATION.md"
    )
    assert spec.is_file()
    raw = spec.read_text(encoding="utf-8")
    text = " ".join(raw.replace("*", " ").lower().split())
    assert "v0.4.0-research-data-contract-schemas" in raw
    assert "0010_normalized_dataset_catalog" in raw
    assert "schema compatibility baseline" in text
    assert "vendor-agnostic" in text
    assert "no vendors reales" in text
    assert "no internet" in text
    assert "no trading" in text
    assert "no pnl/returns" in text
    assert "DATABASE_URL=" not in raw
    assert "postgresql+psycopg://quant:" not in text
    assert "quant_dev_only_not_for_production" not in text


def test_schema_post_tag_release_notes() -> None:
    spec = _ROOT / "docs" / "release" / "DATA_CONTRACT_SCHEMA_POST_TAG_RELEASE_NOTES.md"
    assert spec.is_file()
    raw = spec.read_text(encoding="utf-8")
    text = " ".join(raw.replace("*", " ").lower().split())
    assert "v0.4.0-research-data-contract-schemas" in raw
    assert "681ab7cbcba8af2a5f7a0045a4cdc383b07cc393" in raw
    assert "0010_normalized_dataset_catalog" in raw
    assert "schema compatibility baseline" in text
    assert "vendor_runtime=none" in text
    assert "external_market_data_vendors=disabled" in text
    assert "no vendors reales" in text
    assert "no internet" in text
    assert "no trading" in text
    assert "no pnl/returns" in text
    assert "DATABASE_URL=" not in raw
    assert "postgresql+psycopg://quant:" not in text
    assert "quant_dev_only_not_for_production" not in text
