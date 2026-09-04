"""Offline contract-payload intake. No HTTP, vendors, or trading."""

from __future__ import annotations

import importlib.util
import json
import shutil
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from quant_platform.core.config import Settings
from quant_platform.data.contracts import (
    FakeVendorPayloadProvider,
    VendorContractError,
    VendorDailyBarPayload,
    VendorPayloadBatch,
    assert_offline_contract_package,
    build_contract_payload_intake_plan,
    build_contract_payload_intake_report,
    build_contract_payload_intake_request,
    default_contract_payload_intake_dir,
    default_offline_contract,
    execute_contract_payload_intake,
    hash_contract_payload_intake_plan,
    load_offline_vendor_payload_batch,
    run_contract_payload_intake_regression,
    verify_contract_payload_intake_artifacts,
    write_contract_payload_intake_artifacts,
)
from quant_platform.data.contracts.intake_regression import (
    load_intake_regression_case,
    run_intake_regression_case,
)
from quant_platform.data.contracts.intake_types import (
    INTAKE_MANIFEST_ARTIFACT_NAME,
    INTAKE_PLAN_ARTIFACT_NAME,
    INTAKE_REPORT_ARTIFACT_NAME,
)
from quant_platform.release.constants import (
    DISABLED_CAPABILITIES,
    ENABLED_CAPABILITIES,
)
from quant_platform.release.guards import (
    detect_contracts_networking,
    detect_real_vendor_clients,
)
from quant_platform.simulation.constructs import detect_trading_constructs

_ROOT = Path(__file__).resolve().parents[2]
_PACKAGE = _ROOT / "src" / "quant_platform"
_SCRIPTS = _ROOT / "scripts"
_FIXTURES = _ROOT / "tests" / "fixtures" / "contract_payload_intake"
_INGESTION = datetime(2024, 1, 4, 12, 0, tzinfo=UTC)
_FAKE_HASH = "sha256:" + ("a" * 64)
_VENDOR_FILENAMES = {
    "polygon.py",
    "yfinance.py",
    "yahoo.py",
    "alpaca.py",
    "binance.py",
    "tiingo.py",
}


def _load_script(filename: str):
    path = _SCRIPTS / filename
    spec = importlib.util.spec_from_file_location(filename.replace("-", "_"), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bar(**overrides: object) -> VendorDailyBarPayload:
    base: dict[str, object] = {
        "symbol": "ACME",
        "source_name": "offline_fixture",
        "observation_time": datetime(2024, 1, 2, tzinfo=UTC),
        "available_time": datetime(2024, 1, 3, tzinfo=UTC),
        "ingestion_time": _INGESTION,
        "open": Decimal("10.00"),
        "high": Decimal("11.00"),
        "low": Decimal("9.50"),
        "close": Decimal("10.50"),
        "volume": Decimal("1000"),
        "raw_payload": {"symbol": "ACME"},
        "metadata": {"fixture_id": "unit-acme-bar"},
    }
    base.update(overrides)
    return VendorDailyBarPayload(**base)  # type: ignore[arg-type]


def _batch(*bars: VendorDailyBarPayload) -> VendorPayloadBatch:
    return VendorPayloadBatch(
        source_name="offline_fixture",
        contract=default_offline_contract("offline_fixture"),
        daily_bars=bars,
    )


def test_valid_batch_produces_ok_plan() -> None:
    batch = FakeVendorPayloadProvider(validate=False).load_batch()
    plan = build_contract_payload_intake_plan(batch)
    assert plan.ok is True
    assert plan.write_db is False
    assert plan.planned_daily_bar_count == 1
    assert plan.planned_corporate_action_count == 1
    assert plan.planned_market_session_count == 1
    assert plan.intake_hash == hash_contract_payload_intake_plan(plan)
    assert plan.intake_hash.startswith("sha256:")


def test_invalid_batch_is_rejected() -> None:
    batch = load_offline_vendor_payload_batch(
        _FIXTURES / "invalid_batch_rejected" / "batch.json"
    )
    plan = build_contract_payload_intake_plan(batch)
    assert plan.ok is False
    assert plan.planned_daily_bar_count == 0
    assert plan.rejected_counts.daily_bars == 1
    assert any(item.code == "lookahead" for item in plan.issues)


def test_allow_invalid_plans_valid_rows_without_db_write() -> None:
    good = _bar()
    bad = _bar(
        observation_time=datetime(2024, 1, 3, tzinfo=UTC),
        available_time=datetime(2024, 1, 3, tzinfo=UTC),
        metadata={"fixture_id": "unit-lookahead"},
    )
    batch = _batch(good, bad)
    request = build_contract_payload_intake_request(
        allow_invalid=True,
        write_db=True,
    )
    plan = build_contract_payload_intake_plan(batch, request)
    assert plan.ok is False
    assert plan.allow_invalid is True
    assert plan.write_db is True
    assert plan.planned_daily_bar_count == 1
    assert plan.rejected_counts.daily_bars == 1
    report = execute_contract_payload_intake(None, batch, request)  # type: ignore[arg-type]
    assert report.db_executed is False
    assert report.inserted_counts.total == 0
    assert report.ok is False


def test_execute_without_write_db_flag_raises() -> None:
    batch = FakeVendorPayloadProvider(validate=False).load_batch()
    request = build_contract_payload_intake_request(write_db=False)
    with pytest.raises(VendorContractError) as exc:
        execute_contract_payload_intake(None, batch, request)  # type: ignore[arg-type]
    assert exc.value.code == "write_db_required"


def test_dry_run_report_does_not_execute_db() -> None:
    batch = FakeVendorPayloadProvider(validate=False).load_batch()
    plan = build_contract_payload_intake_plan(batch)
    report = build_contract_payload_intake_report(plan)
    assert plan.write_db is False
    assert report.db_executed is False
    assert report.inserted_counts.total == 0
    assert report.skipped_counts.total == 0


def test_plan_hash_is_stable() -> None:
    batch = FakeVendorPayloadProvider(validate=False).load_batch()
    first = build_contract_payload_intake_plan(batch)
    second = build_contract_payload_intake_plan(batch)
    assert first.intake_hash == second.intake_hash
    assert hash_contract_payload_intake_plan(first.as_mapping()) == first.intake_hash


def test_plan_hash_changes_with_payload() -> None:
    first = build_contract_payload_intake_plan(_batch(_bar()))
    second = build_contract_payload_intake_plan(
        _batch(_bar(volume=Decimal("2000"), raw_payload={"symbol": "ACME", "v": "2"}))
    )
    assert first.intake_hash != second.intake_hash


def test_artifacts_use_relative_paths(tmp_path: Path) -> None:
    batch = FakeVendorPayloadProvider(validate=False).load_batch()
    plan = build_contract_payload_intake_plan(batch)
    report = build_contract_payload_intake_report(plan)
    manifest = write_contract_payload_intake_artifacts(plan, report, tmp_path)
    for item in manifest.artifacts:
        assert not Path(item.path).is_absolute()
        assert ".." not in item.path
        assert (tmp_path / item.path).is_file()
    checked = verify_contract_payload_intake_artifacts(tmp_path)
    assert checked.ok is True


def test_integrity_rejects_path_traversal(tmp_path: Path) -> None:
    batch = FakeVendorPayloadProvider(validate=False).load_batch()
    plan = build_contract_payload_intake_plan(batch)
    report = build_contract_payload_intake_report(plan)
    write_contract_payload_intake_artifacts(plan, report, tmp_path)
    manifest_path = tmp_path / INTAKE_MANIFEST_ARTIFACT_NAME
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["artifacts"] = [
        {"name": "escape", "path": "../secret.json", "kind": "json"}
    ]
    manifest_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    checked = verify_contract_payload_intake_artifacts(tmp_path)
    assert checked.ok is False
    assert "path_escape" in {item.code for item in checked.issues}


def test_integrity_rejects_secrets(tmp_path: Path) -> None:
    batch = FakeVendorPayloadProvider(validate=False).load_batch()
    plan = build_contract_payload_intake_plan(batch)
    report = build_contract_payload_intake_report(plan)
    write_contract_payload_intake_artifacts(plan, report, tmp_path)
    report_path = tmp_path / INTAKE_REPORT_ARTIFACT_NAME
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload["notes"] = "postgresql://quant:x@localhost/db"
    report_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    checked = verify_contract_payload_intake_artifacts(tmp_path)
    assert checked.ok is False
    assert "secret_in_metadata" in {item.code for item in checked.issues}


def test_integrity_rejects_trading_and_performance_terms(tmp_path: Path) -> None:
    batch = FakeVendorPayloadProvider(validate=False).load_batch()
    plan = build_contract_payload_intake_plan(batch)
    report = build_contract_payload_intake_report(plan)
    write_contract_payload_intake_artifacts(plan, report, tmp_path)
    plan_path = tmp_path / INTAKE_PLAN_ARTIFACT_NAME
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    payload["sharpe"] = 1.2
    payload["pnl"] = 0
    payload["returns"] = 0
    plan_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    checked = verify_contract_payload_intake_artifacts(tmp_path)
    assert checked.ok is False
    codes = {item.code for item in checked.issues}
    assert "forbidden_metric" in codes or "forbidden_term" in codes


def test_scripts_json_returns_valid_json(
    monkeypatch: pytest.MonkeyPatch,
    research_settings: Settings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runner = _load_script("run-contract-payload-intake.py")
    monkeypatch.setattr(runner, "get_settings", lambda: research_settings)
    code = runner.main(
        [
            "--json",
            "--fixture-dir",
            str(_FIXTURES / "valid_dry_run"),
        ]
    )
    captured = capsys.readouterr()
    assert code == 0
    payload = json.loads(captured.out)
    assert payload["kind"] == "contract_payload_intake_report"
    assert payload["ok"] is True
    assert payload["write_db"] is False
    assert payload["db_executed"] is False
    assert "DATABASE_URL" not in captured.out
    assert "postgresql+psycopg://" not in captured.out
    regression = _load_script("run-contract-payload-intake-regression.py")
    monkeypatch.setattr(regression, "get_settings", lambda: research_settings)
    regression_code = regression.main(["--json"])
    regression_out = capsys.readouterr()
    assert regression_code == 0
    matrix = json.loads(regression_out.out)
    assert matrix["kind"] == "contract_payload_intake_regression_report"
    assert matrix["ok"] is True
    assert "DATABASE_URL" not in regression_out.out


def test_golden_matrix_passes() -> None:
    report = run_contract_payload_intake_regression()
    assert report.ok is True
    assert report.case_count == 5
    assert report.failed_count == 0
    assert report.report_hash.startswith("sha256:")


def test_regression_fixtures_load() -> None:
    root = default_contract_payload_intake_dir()
    names = sorted(item.name for item in root.iterdir() if item.is_dir())
    assert names == [
        "forbidden_term_rejected",
        "invalid_batch_rejected",
        "mixed_payload_counts",
        "secret_rejected",
        "valid_dry_run",
    ]
    for name in names:
        case = load_intake_regression_case(root / name)
        assert case.case_id == name
        assert case.expected.intake_hash
        assert case.expected.intake_hash.startswith("sha256:")


def test_regression_detects_hash_drift(tmp_path: Path) -> None:
    dest = tmp_path / "valid_dry_run"
    shutil.copytree(_FIXTURES / "valid_dry_run", dest)
    expected = json.loads((dest / "expected.json").read_text(encoding="utf-8"))
    expected["expected_intake_hash"] = _FAKE_HASH
    (dest / "expected.json").write_text(
        json.dumps(expected, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    case = load_intake_regression_case(dest)
    result = run_intake_regression_case(case, fixtures_root=tmp_path)
    assert result.passed is False
    assert any(item.code == "intake_hash_changed" for item in result.issues)


def test_no_real_vendors_or_network_imports() -> None:
    assert detect_contracts_networking(_PACKAGE) == ()
    assert detect_real_vendor_clients(_PACKAGE) == ()
    assert_offline_contract_package(_PACKAGE)
    enabled = set(ENABLED_CAPABILITIES)
    disabled = set(DISABLED_CAPABILITIES)
    assert "contract_payload_intake_offline" in enabled
    assert "external_market_data_vendors" in disabled
    contracts = _PACKAGE / "data" / "contracts"
    present = {path.name for path in contracts.glob("*.py")}
    assert present.isdisjoint(_VENDOR_FILENAMES)
    findings = detect_trading_constructs(package_root=_PACKAGE)
    assert findings == ()
    blob = " ".join(
        path.read_text(encoding="utf-8") for path in contracts.glob("intake*.py")
    )
    lowered = blob.lower()
    assert "import requests" not in lowered
    assert "import httpx" not in lowered
    assert "import aiohttp" not in lowered


def test_intake_remote_verification_doc() -> None:
    spec = (
        _ROOT
        / "docs"
        / "release"
        / "CONTRACT_PAYLOAD_INTAKE_REMOTE_RELEASE_VERIFICATION.md"
    )
    assert spec.is_file()
    raw = spec.read_text(encoding="utf-8")
    text = " ".join(raw.replace("*", " ").lower().split())
    assert "v0.5.0-research-intake-bridge" in raw
    assert "0010_normalized_dataset_catalog" in raw
    assert "dry-run" in text
    assert "--write-db" in raw
    assert "vendor-agnostic" in text
    assert "no vendors reales" in text
    assert "no internet" in text
    assert "no trading" in text
    assert "no pnl/returns" in text
    assert "DATABASE_URL=" not in raw
    assert "postgresql+psycopg://quant:" not in text
    assert "quant_dev_only_not_for_production" not in text


def test_intake_post_tag_release_notes() -> None:
    spec = (
        _ROOT / "docs" / "release" / "CONTRACT_PAYLOAD_INTAKE_POST_TAG_RELEASE_NOTES.md"
    )
    assert spec.is_file()
    raw = spec.read_text(encoding="utf-8")
    text = " ".join(raw.replace("*", " ").lower().split())
    assert "v0.5.0-research-intake-bridge" in raw
    assert "807bd6b4f19afd57141981ef664a25b205d6cfb1" in raw
    assert "0010_normalized_dataset_catalog" in raw
    assert "dry-run" in text
    assert "--write-db" in raw
    assert "vendor_runtime=none" in text
    assert "external_market_data_vendors=disabled" in text
    assert "no vendors reales" in text
    assert "no internet" in text
    assert "no trading" in text
    assert "no pnl/returns" in text
    assert "DATABASE_URL=" not in raw
    assert "postgresql+psycopg://quant:" not in text
    assert "quant_dev_only_not_for_production" not in text
