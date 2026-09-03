"""Research release-candidate checks without Docker. No trading."""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from quant_platform.backtest.policy_regression import (
    default_policy_regression_matrix_path,
)
from quant_platform.core.config import Settings
from quant_platform.release.checks import run_research_release_checks
from quant_platform.release.constants import (
    DISABLED_CAPABILITIES,
    EXPECTED_ALEMBIC_HEAD,
)
from quant_platform.release.status import (
    alembic_script_heads,
    build_release_status,
    hash_release_status_report,
    repository_root,
)

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "policy_regression"
_NORM_FIXTURES = (
    Path(__file__).resolve().parents[1] / "fixtures" / "normalization_regression"
)
_FAKE_HASH = "sha256:" + ("a" * 64)


def _load_script(filename: str):
    path = _SCRIPTS / filename
    spec = importlib.util.spec_from_file_location(filename.replace("-", "_"), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _assert_no_secrets(blob: str) -> None:
    lowered = blob.lower()
    assert "postgresql+psycopg://" not in lowered
    assert "quant_dev_only_not_for_production" not in lowered
    assert "://quant:" not in lowered
    assert "DATABASE_URL" not in blob


def test_status_report_serializes_without_secrets(
    research_settings: Settings,
) -> None:
    report = build_release_status(settings=research_settings)
    blob = json.dumps(report.as_mapping(), sort_keys=True)
    _assert_no_secrets(blob)
    assert report.package_version
    assert report.alembic_head_expected == EXPECTED_ALEMBIC_HEAD
    assert report.registered_policy_count >= 6
    assert report.regression_case_count >= 18
    assert report.report_hash == hash_release_status_report(report)
    assert report.report_hash == hash_release_status_report(report.as_mapping())
    assert report.final_freeze_ready is True
    assert report.evidence_bundle_available is True
    assert report.evidence_bundle_fixture_reuse_supported is True
    assert report.alembic_head_expected == EXPECTED_ALEMBIC_HEAD
    disabled = set(report.capabilities.disabled)
    assert "paper_trading" in disabled
    assert "live_trading" in disabled
    assert "brokers" in disabled
    assert "ai_runtime" in disabled


def test_expected_alembic_head_matches_scripts() -> None:
    heads = alembic_script_heads(repository_root())
    assert heads == (EXPECTED_ALEMBIC_HEAD,)


def test_disabled_capabilities_list_trading_paper_live_brokers_ai() -> None:
    disabled = set(DISABLED_CAPABILITIES)
    for name in (
        "paper_trading",
        "live_trading",
        "brokers",
        "ai_runtime",
        "order_execution",
        "portfolio",
        "signals",
        "strategies",
    ):
        assert name in disabled


def test_release_check_detects_incorrect_app_mode(
    research_settings: Settings,
) -> None:
    report = run_research_release_checks(
        settings=research_settings,
        skip_db=True,
        skip_compose=True,
        skip_regression=True,
        skip_normalization_regression=True,
        skip_imports=True,
        research_mode=False,
    )
    assert report.ok is False
    codes = {item.code for item in report.checks if item.status == "error"}
    assert "app_mode_not_research" in codes


def test_release_check_detects_policy_regression_failure(
    research_settings: Settings, tmp_path: Path
) -> None:
    shutil.copy(_FIXTURES / "simple_bars.jsonl", tmp_path / "simple_bars.jsonl")
    matrix = {
        "kind": "policy_regression_matrix",
        "format_version": 1,
        "cases": [
            {
                "case_id": "noop-drift",
                "description": "intentional hash drift",
                "fixture_path": "simple_bars.jsonl",
                "policy_name": "noop",
                "policy_config": {},
                "expected_policy_output_hash": _FAKE_HASH,
                "expected_observation_count": 0,
                "expected_counts_by_kind": {},
                "expected_counts_by_severity": {},
            }
        ],
    }
    path = tmp_path / "matrix.json"
    path.write_text(json.dumps(matrix) + "\n", encoding="utf-8")
    report = run_research_release_checks(
        settings=research_settings,
        matrix_path=path,
        skip_db=True,
        skip_compose=True,
        skip_imports=True,
        skip_normalization_regression=True,
    )
    assert report.ok is False
    names = {item.name: item.status for item in report.checks if item.status == "error"}
    assert names.get("policy_regression") == "error"


def test_release_check_detects_normalization_regression_failure(
    research_settings: Settings, tmp_path: Path
) -> None:
    dest = tmp_path / "split_2_for_1"
    shutil.copytree(_NORM_FIXTURES / "split_2_for_1", dest)
    expected = json.loads((dest / "expected.json").read_text(encoding="utf-8"))
    expected["expected_dataset_hash"] = _FAKE_HASH
    (dest / "expected.json").write_text(
        json.dumps(expected, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    report = run_research_release_checks(
        settings=research_settings,
        skip_db=True,
        skip_compose=True,
        skip_regression=True,
        skip_imports=True,
        normalization_fixtures_dir=tmp_path,
    )
    assert report.ok is False
    names = {item.name: item.status for item in report.checks if item.status == "error"}
    assert names.get("normalization_regression") == "error"


def test_release_check_detects_forbidden_construct(
    research_settings: Settings, tmp_path: Path
) -> None:
    (tmp_path / "strategies").mkdir()
    (tmp_path / "strategies" / "__init__.py").write_text("", encoding="utf-8")
    report = run_research_release_checks(
        settings=research_settings,
        package_root=tmp_path,
        skip_db=True,
        skip_compose=True,
        skip_regression=True,
        skip_normalization_regression=True,
        skip_imports=True,
    )
    assert report.ok is False
    assert report.trading_constructs_detected is True
    codes = {item.code for item in report.checks if item.status == "error"}
    assert "trading_construct_detected" in codes or "forbidden_package" in codes


def test_release_check_json_script_has_no_database_url(
    monkeypatch: pytest.MonkeyPatch,
    research_settings: Settings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runner = _load_script("research-release-check.py")
    monkeypatch.setattr(runner, "get_settings", lambda: research_settings)
    code = runner.main(["--json", "--skip-db", "--skip-compose", "--skip-regression"])
    captured = capsys.readouterr()
    assert code == 0
    payload = json.loads(captured.out)
    blob = captured.out + captured.err
    _assert_no_secrets(blob)
    assert payload["kind"] == "research_release_status"
    assert payload["ok"] is True
    assert payload["alembic_head_expected"] == EXPECTED_ALEMBIC_HEAD
    status = _load_script("research-status.py")
    monkeypatch.setattr(status, "get_settings", lambda: research_settings)
    status_code = status.main(["--json"])
    status_out = capsys.readouterr()
    assert status_code == 0
    status_payload = json.loads(status_out.out)
    _assert_no_secrets(status_out.out + status_out.err)
    assert status_payload["registered_policy_count"] >= 6
    assert status_payload["final_freeze_ready"] is True
    assert status_payload["evidence_bundle_available"] is True
    assert status_payload["alembic_head_expected"] == EXPECTED_ALEMBIC_HEAD
    assert "paper_trading" in status_payload["capabilities"]["disabled"]
    assert "live_trading" in status_payload["capabilities"]["disabled"]
    assert "brokers" in status_payload["capabilities"]["disabled"]
    assert "ai_runtime" in status_payload["capabilities"]["disabled"]


def test_release_scripts_parse_help() -> None:
    checker = _load_script("research-release-check.py")
    with pytest.raises(SystemExit) as help_exc:
        checker.main(["--help"])
    assert help_exc.value.code == 0
    status = _load_script("research-status.py")
    with pytest.raises(SystemExit) as status_help:
        status.main(["--help"])
    assert status_help.value.code == 0


def test_golden_matrix_still_used_by_default() -> None:
    path = default_policy_regression_matrix_path()
    assert path.name == "matrix.json"
    assert path.is_file()
