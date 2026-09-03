"""Offline data-contract conformance reports. No HTTP, vendors, or trading."""

from __future__ import annotations

import importlib.util
import json
import shutil
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from quant_platform.core.config import Settings
from quant_platform.data.contracts import (
    FakeVendorPayloadProvider,
    VendorContractError,
    VendorCorporateActionPayload,
    VendorDailyBarPayload,
    VendorMarketSessionPayload,
    VendorPayloadBatch,
    assert_offline_contract_package,
    build_data_contract_conformance_report,
    default_data_contract_conformance_dir,
    default_offline_contract,
    hash_data_contract_conformance_report,
    load_offline_vendor_payload_batch,
    run_data_contract_conformance_regression,
    verify_data_contract_conformance_artifacts,
    write_data_contract_conformance_artifacts,
)
from quant_platform.data.contracts.conformance_regression import (
    compare_conformance_regression_result,
    load_conformance_regression_case,
    run_conformance_regression_case,
)
from quant_platform.data.contracts.conformance_regression_types import (
    ConformanceRegressionActual,
    ConformanceRegressionCode,
    ConformanceRegressionExpected,
)
from quant_platform.data.contracts.conformance_types import (
    CONFORMANCE_MANIFEST_ARTIFACT_NAME,
    CONFORMANCE_REPORT_ARTIFACT_NAME,
    DataContractConformanceReport,
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
_FIXTURES = _ROOT / "tests" / "fixtures" / "data_contract_conformance"
_INGESTION = datetime(2024, 1, 4, 12, 0, tzinfo=UTC)
_FAKE_HASH = "sha256:" + ("a" * 64)


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
        "open": Decimal("10"),
        "high": Decimal("11"),
        "low": Decimal("9.5"),
        "close": Decimal("10.5"),
        "volume": Decimal("1000"),
        "raw_payload": {"symbol": "ACME"},
        "metadata": {"fixture_id": "acme-bar"},
    }
    base.update(overrides)
    return VendorDailyBarPayload(**base)  # type: ignore[arg-type]


def _action(**overrides: object) -> VendorCorporateActionPayload:
    base: dict[str, object] = {
        "symbol": "ACME",
        "source_name": "offline_fixture",
        "action_type": "split",
        "effective_time": datetime(2024, 1, 3, tzinfo=UTC),
        "available_time": datetime(2024, 1, 2, 18, 0, tzinfo=UTC),
        "observation_time": datetime(2024, 1, 2, 18, 0, tzinfo=UTC),
        "ingestion_time": _INGESTION,
        "quantity_before": Decimal("1"),
        "quantity_after": Decimal("2"),
        "raw_payload": {"action_type": "split"},
        "metadata": {"fixture_id": "acme-split"},
    }
    base.update(overrides)
    return VendorCorporateActionPayload(**base)  # type: ignore[arg-type]


def _session(**overrides: object) -> VendorMarketSessionPayload:
    base: dict[str, object] = {
        "source_name": "offline_fixture",
        "calendar_code": "TEST",
        "session_date": date(2024, 1, 2),
        "observation_time": datetime(2024, 1, 2, tzinfo=UTC),
        "available_time": datetime(2024, 1, 2, 21, 0, tzinfo=UTC),
        "ingestion_time": _INGESTION,
        "session_kind": "open",
        "is_open": True,
        "symbol": "ACME",
        "raw_payload": {"session_kind": "open"},
        "metadata": {"fixture_id": "acme-session"},
    }
    base.update(overrides)
    return VendorMarketSessionPayload(**base)  # type: ignore[arg-type]


def _batch(
    *,
    bars: tuple[VendorDailyBarPayload, ...] | None = None,
    actions: tuple[VendorCorporateActionPayload, ...] | None = None,
    sessions: tuple[VendorMarketSessionPayload, ...] | None = None,
) -> VendorPayloadBatch:
    return VendorPayloadBatch(
        source_name="offline_fixture",
        contract=default_offline_contract("offline_fixture"),
        daily_bars=bars if bars is not None else (_bar(),),
        corporate_actions=actions if actions is not None else (_action(),),
        market_sessions=sessions if sessions is not None else (_session(),),
    )


def _issue_codes(report: DataContractConformanceReport) -> set[str]:
    return {item.code for item in report.issues}


def test_valid_batch_produces_ok_report() -> None:
    report = build_data_contract_conformance_report(_batch())
    assert report.ok is True
    assert report.summary.validation_ok is True
    assert report.summary.forbidden_terms_ok is True
    assert report.summary.offline_only_ok is True
    assert report.summary.issue_counts.total == 0
    assert report.conformance_hash.startswith("sha256:")


def test_invalid_available_time_produces_lookahead_issue() -> None:
    observation = datetime(2024, 1, 2, tzinfo=UTC)
    report = build_data_contract_conformance_report(
        _batch(bars=(_bar(available_time=observation),), actions=(), sessions=())
    )
    assert report.ok is False
    assert report.summary.validation_ok is False
    assert "lookahead" in _issue_codes(report)


def test_secret_metadata_produces_issue() -> None:
    report = build_data_contract_conformance_report(
        _batch(
            bars=(_bar(metadata={"token": "test-token-not-real"}),),
            actions=(),
            sessions=(),
        )
    )
    assert report.ok is False
    assert "secret_in_metadata" in _issue_codes(report)


def test_forbidden_trading_term_produces_issue() -> None:
    report = build_data_contract_conformance_report(
        _batch(
            bars=(_bar(metadata={"note": "must not mention PnL or returns"}),),
            actions=(),
            sessions=(),
        )
    )
    assert report.ok is False
    assert report.summary.forbidden_terms_ok is False
    assert "forbidden_term" in _issue_codes(report)


def test_report_hash_is_stable() -> None:
    first = build_data_contract_conformance_report(_batch())
    second = build_data_contract_conformance_report(_batch())
    assert first.conformance_hash == second.conformance_hash
    assert first.conformance_hash == hash_data_contract_conformance_report(first)
    assert first.conformance_hash == hash_data_contract_conformance_report(
        first.as_mapping()
    )


def test_report_hash_changes_with_payload() -> None:
    original = build_data_contract_conformance_report(_batch())
    changed = build_data_contract_conformance_report(
        _batch(bars=(_bar(close=Decimal("10.75")),))
    )
    assert original.conformance_hash != changed.conformance_hash
    assert original.summary.batch_hash != changed.summary.batch_hash


def test_artifacts_use_relative_paths(tmp_path: Path) -> None:
    report = build_data_contract_conformance_report(_batch())
    manifest = write_data_contract_conformance_artifacts(
        report,
        tmp_path,
        batch=_batch(),
        include_source_payload=True,
    )
    payload = json.loads((tmp_path / CONFORMANCE_MANIFEST_ARTIFACT_NAME).read_text())
    for item in payload["artifacts"]:
        path = item["path"]
        assert not Path(path).is_absolute()
        assert ".." not in Path(path).parts
        assert (tmp_path / path).is_file()
    assert payload["conformance_hash"] == report.conformance_hash
    assert payload["offline_only_ok"] is True
    names = {item.name for item in manifest.artifacts}
    assert "source_payload_batch" in names


def test_integrity_accepts_valid_artifacts(tmp_path: Path) -> None:
    report = build_data_contract_conformance_report(_batch())
    write_data_contract_conformance_artifacts(report, tmp_path)
    checked = verify_data_contract_conformance_artifacts(tmp_path)
    assert checked.ok is True
    assert checked.error_count == 0


def test_integrity_rejects_path_traversal(tmp_path: Path) -> None:
    report = build_data_contract_conformance_report(_batch())
    write_data_contract_conformance_artifacts(report, tmp_path)
    manifest_path = tmp_path / CONFORMANCE_MANIFEST_ARTIFACT_NAME
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["artifacts"] = [
        {"name": "report", "path": CONFORMANCE_REPORT_ARTIFACT_NAME, "kind": "json"},
        {"name": "escape", "path": "../secret.json", "kind": "json"},
    ]
    manifest_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    checked = verify_data_contract_conformance_artifacts(tmp_path)
    assert checked.ok is False
    assert "path_escape" in {item.code for item in checked.issues}


def test_regression_fixtures_load() -> None:
    root = default_data_contract_conformance_dir()
    names = sorted(item.name for item in root.iterdir() if item.is_dir())
    assert names == [
        "forbidden_term_in_metadata",
        "invalid_time_order",
        "mixed_batch_with_issues",
        "secret_in_metadata",
        "valid_batch",
    ]
    for name in names:
        case = load_conformance_regression_case(root / name)
        assert case.case_id == name
        assert case.expected.issue_count is not None
        assert case.expected.conformance_hash
        assert case.expected.conformance_hash.startswith("sha256:")
        assert case.expected.batch_hash
        assert case.expected.batch_hash.startswith("sha256:")


def test_regression_valid_batch_passes() -> None:
    root = default_data_contract_conformance_dir()
    case = load_conformance_regression_case(root / "valid_batch")
    result = run_conformance_regression_case(case, fixtures_root=root)
    assert result.passed is True
    assert result.actual is not None
    assert result.actual.ok is True
    assert result.actual.issue_count == 0


def test_regression_detects_hash_drift(tmp_path: Path) -> None:
    dest = tmp_path / "valid_batch"
    shutil.copytree(_FIXTURES / "valid_batch", dest)
    expected = json.loads((dest / "expected.json").read_text(encoding="utf-8"))
    expected["expected_conformance_hash"] = _FAKE_HASH
    (dest / "expected.json").write_text(
        json.dumps(expected, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    case = load_conformance_regression_case(dest)
    result = run_conformance_regression_case(case, fixtures_root=tmp_path)
    assert result.passed is False
    codes = {item.code for item in result.issues}
    assert ConformanceRegressionCode.CONFORMANCE_HASH_CHANGED.value in codes


def test_regression_compare_detects_issue_count_drift() -> None:
    actual = ConformanceRegressionActual(
        case_id="demo",
        conformance_hash=_FAKE_HASH,
        batch_hash=_FAKE_HASH,
        issue_count=1,
        issue_codes=("lookahead",),
        validation_ok=False,
        forbidden_terms_ok=True,
        offline_only_ok=True,
        ok=False,
    )
    expected = ConformanceRegressionExpected(
        conformance_hash=_FAKE_HASH,
        batch_hash=_FAKE_HASH,
        issue_count=0,
        issue_codes=(),
        validation_ok=True,
        forbidden_terms_ok=True,
        offline_only_ok=True,
        ok=True,
    )
    issues = compare_conformance_regression_result(actual, expected)
    codes = {item.code for item in issues}
    assert ConformanceRegressionCode.ISSUE_COUNT_CHANGED.value in codes
    assert ConformanceRegressionCode.ISSUE_CODES_CHANGED.value in codes


def test_golden_matrix_passes() -> None:
    report = run_data_contract_conformance_regression()
    assert report.ok is True
    assert report.case_count == 5
    assert report.failed_count == 0
    assert report.report_hash.startswith("sha256:")


def test_scripts_json_returns_valid_json(
    monkeypatch: pytest.MonkeyPatch,
    research_settings: Settings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runner = _load_script("run-data-contract-conformance.py")
    monkeypatch.setattr(runner, "get_settings", lambda: research_settings)
    code = runner.main(
        [
            "--json",
            "--fixture-dir",
            str(_FIXTURES / "valid_batch"),
        ]
    )
    captured = capsys.readouterr()
    assert code == 0
    payload = json.loads(captured.out)
    assert payload["kind"] == "data_contract_conformance_report"
    assert payload["ok"] is True
    assert "DATABASE_URL" not in captured.out
    regression = _load_script("run-data-contract-conformance-regression.py")
    monkeypatch.setattr(regression, "get_settings", lambda: research_settings)
    regression_code = regression.main(["--json"])
    regression_out = capsys.readouterr()
    assert regression_code == 0
    matrix = json.loads(regression_out.out)
    assert matrix["kind"] == "data_contract_conformance_regression_report"
    assert matrix["ok"] is True
    assert "DATABASE_URL" not in regression_out.out


def test_offline_package_assertion_blocks_networking(tmp_path: Path) -> None:
    assert_offline_contract_package(_PACKAGE)
    contracts = tmp_path / "data" / "contracts"
    contracts.mkdir(parents=True)
    (contracts / "__init__.py").write_text("", encoding="utf-8")
    (contracts / "client.py").write_text("import requests\n", encoding="utf-8")
    with pytest.raises(VendorContractError) as exc:
        assert_offline_contract_package(tmp_path)
    assert exc.value.code == "networking_import"


def test_no_real_vendor_implemented() -> None:
    assert detect_contracts_networking(_PACKAGE) == ()
    assert detect_real_vendor_clients(_PACKAGE) == ()
    enabled = set(ENABLED_CAPABILITIES)
    disabled = set(DISABLED_CAPABILITIES)
    assert "data_contract_conformance" in enabled
    assert "vendor_agnostic_data_contracts" in enabled
    assert "external_market_data_vendors" in disabled
    contracts = _PACKAGE / "data" / "contracts"
    forbidden = {
        "polygon.py",
        "yfinance.py",
        "alpaca.py",
        "binance.py",
        "yahoo.py",
        "tiingo.py",
        "iex.py",
        "bloomberg.py",
    }
    present = {path.name for path in contracts.glob("*.py")}
    assert present.isdisjoint(forbidden)
    findings = detect_trading_constructs(package_root=_PACKAGE)
    assert findings == ()


def test_fixture_loader_does_not_require_validation() -> None:
    batch = load_offline_vendor_payload_batch(_FIXTURES / "invalid_time_order")
    assert len(batch.daily_bars) == 1
    provider = FakeVendorPayloadProvider(
        fixtures_path=_FIXTURES / "valid_batch",
        validate=True,
    )
    loaded = provider.load_batch()
    assert loaded.source_name == "offline_fixture"


def test_conformance_docs_exist_without_database_url() -> None:
    spec = _ROOT / "docs" / "data" / "DATA_CONTRACT_CONFORMANCE.md"
    assert spec.is_file()
    text = spec.read_text(encoding="utf-8")
    assert "DATABASE_URL" not in text
    assert "postgresql+psycopg://" not in text.lower()
    lowered = text.lower()
    assert "offline" in lowered
    assert "not a trading" in lowered or "not trading" in lowered
    assert "pnl" in lowered
    assert "returns" in lowered


def test_data_contract_remote_verification_doc() -> None:
    spec = _ROOT / "docs" / "release" / "DATA_CONTRACT_REMOTE_RELEASE_VERIFICATION.md"
    assert spec.is_file()
    raw = spec.read_text(encoding="utf-8")
    text = " ".join(raw.replace("*", " ").lower().split())
    assert "v0.3.0-research-data-contracts" in raw
    assert "0010_normalized_dataset_catalog" in raw
    assert "vendor-agnostic" in text
    assert "no vendors reales" in text
    assert "no internet" in text
    assert "no trading" in text
    assert "no pnl/returns" in text
    assert "DATABASE_URL=" not in raw
    assert "postgresql+psycopg://quant:" not in text
    assert "quant_dev_only_not_for_production" not in text


def test_data_contract_post_tag_release_notes() -> None:
    spec = _ROOT / "docs" / "release" / "DATA_CONTRACT_POST_TAG_RELEASE_NOTES.md"
    assert spec.is_file()
    raw = spec.read_text(encoding="utf-8")
    text = " ".join(raw.replace("*", " ").lower().split())
    assert "v0.3.0-research-data-contracts" in raw
    assert "4dd805f9acb72ea03e812db2b39bf072b5ddd3a1" in raw
    assert "0010_normalized_dataset_catalog" in raw
    assert "vendor_runtime=none" in text
    assert "external_market_data_vendors=disabled" in text
    assert "no vendors reales" in text
    assert "no internet" in text
    assert "no trading" in text
    assert "no pnl/returns" in text
    assert "DATABASE_URL=" not in raw
    assert "postgresql+psycopg://quant:" not in text
    assert "quant_dev_only_not_for_production" not in text
