"""Research-policy regression matrix without Docker. No trading."""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from quant_platform.backtest.errors import BacktestError, BacktestErrorCode
from quant_platform.backtest.policy_regression import (
    compare_policy_regression_result,
    default_policy_regression_matrix_path,
    hash_policy_regression_report,
    load_policy_regression_matrix,
    run_policy_regression_case,
    run_policy_regression_matrix,
    scan_policy_regression_payload,
)
from quant_platform.backtest.policy_regression_artifacts import (
    write_policy_regression_artifacts,
)
from quant_platform.backtest.policy_regression_types import (
    POLICY_REGRESSION_ACTUALS_ARTIFACT_NAME,
    POLICY_REGRESSION_REPORT_ARTIFACT_NAME,
    PolicyRegressionActual,
    PolicyRegressionCase,
    PolicyRegressionCode,
    PolicyRegressionExpected,
)
from quant_platform.backtest.types import ALLOWED_POLICY_NAMES
from quant_platform.core.config import Settings
from quant_platform.simulation.constructs import (
    FORBIDDEN_PACKAGE_NAMES,
    FORBIDDEN_TABLE_NAMES,
    detect_trading_constructs,
)
from quant_platform.simulation.events import EVENT_PRIORITY
from quant_platform.storage.database import Base

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "policy_regression"
_FAKE_HASH = "sha256:" + ("a" * 64)


def _load_script(filename: str):
    path = _SCRIPTS / filename
    spec = importlib.util.spec_from_file_location(filename.replace("-", "_"), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_matrix(path: Path, cases: list[dict[str, object]]) -> Path:
    payload = {
        "kind": "policy_regression_matrix",
        "format_version": 1,
        "cases": cases,
    }
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8")
    return path


def _case_payload(
    *,
    case_id: str,
    fixture_path: str = "simple_bars.jsonl",
    policy_name: str = "noop",
    policy_config: dict[str, object] | None = None,
    expected_hash: str | None = None,
    expected_count: int | None = None,
    expected_kinds: dict[str, int] | None = None,
    expected_severities: dict[str, int] | None = None,
    description: str = "temporary regression case",
) -> dict[str, object]:
    return {
        "case_id": case_id,
        "description": description,
        "fixture_path": fixture_path,
        "policy_name": policy_name,
        "policy_config": {} if policy_config is None else policy_config,
        "expected_policy_output_hash": expected_hash,
        "expected_observation_count": expected_count,
        "expected_counts_by_kind": expected_kinds,
        "expected_counts_by_severity": expected_severities,
    }


def test_load_valid_matrix() -> None:
    cases = load_policy_regression_matrix(default_policy_regression_matrix_path())
    assert len(cases) >= 18
    names = {item.policy_name for item in cases}
    assert names == set(ALLOWED_POLICY_NAMES)
    for name in ALLOWED_POLICY_NAMES:
        matching = [item for item in cases if item.policy_name == name]
        assert len(matching) >= 3
        configs = [item.policy_config for item in matching]
        assert any(item != {} for item in configs)


def test_missing_fixture_fails(tmp_path: Path) -> None:
    shutil.copy(_FIXTURES / "simple_bars.jsonl", tmp_path / "simple_bars.jsonl")
    matrix = _write_matrix(
        tmp_path / "matrix.json",
        [_case_payload(case_id="missing", fixture_path="absent.jsonl")],
    )
    report = run_policy_regression_matrix(matrix)
    assert report.ok is False
    codes = [issue.code for issue in report.results[0].issues]
    assert PolicyRegressionCode.MISSING_FIXTURE.value in codes


def test_unknown_policy_fails(tmp_path: Path) -> None:
    shutil.copy(_FIXTURES / "simple_bars.jsonl", tmp_path / "simple_bars.jsonl")
    matrix = _write_matrix(
        tmp_path / "matrix.json",
        [_case_payload(case_id="unknown", policy_name="momentum")],
    )
    report = run_policy_regression_matrix(matrix)
    assert report.ok is False
    codes = [issue.code for issue in report.results[0].issues]
    assert PolicyRegressionCode.UNKNOWN_POLICY.value in codes


def test_invalid_policy_config_fails(tmp_path: Path) -> None:
    shutil.copy(_FIXTURES / "simple_bars.jsonl", tmp_path / "simple_bars.jsonl")
    matrix = _write_matrix(
        tmp_path / "matrix.json",
        [
            _case_payload(
                case_id="bad-config",
                policy_name="data_quality",
                policy_config={"not_a_key": True},
            )
        ],
    )
    report = run_policy_regression_matrix(matrix)
    assert report.ok is False
    codes = [issue.code for issue in report.results[0].issues]
    assert PolicyRegressionCode.INVALID_POLICY_CONFIG.value in codes


def test_policy_output_hash_is_stable() -> None:
    cases = load_policy_regression_matrix(default_policy_regression_matrix_path())
    case = next(item for item in cases if item.case_id == "data-quality-simple-bars")
    root = default_policy_regression_matrix_path().parent
    first = run_policy_regression_case(case, fixture_root=root)
    second = run_policy_regression_case(case, fixture_root=root)
    assert first.passed is True
    assert second.passed is True
    assert first.actual is not None
    assert second.actual is not None
    assert first.actual.policy_output_hash == second.actual.policy_output_hash
    assert first.actual.policy_output_hash == case.expected.policy_output_hash


def test_hash_change_is_detected() -> None:
    actual = PolicyRegressionActual(
        case_id="hash-drift",
        policy_name="noop",
        policy_config={},
        policy_output_hash=_FAKE_HASH,
        observation_count=0,
        counts_by_kind={},
        counts_by_severity={},
        integrity_ok=True,
    )
    issues = compare_policy_regression_result(
        actual,
        PolicyRegressionExpected(policy_output_hash="sha256:" + ("b" * 64)),
    )
    assert any(
        item.code == PolicyRegressionCode.POLICY_OUTPUT_HASH_CHANGED.value
        for item in issues
    )


def test_count_change_is_detected() -> None:
    actual = PolicyRegressionActual(
        case_id="count-drift",
        policy_name="noop",
        policy_config={},
        policy_output_hash=_FAKE_HASH,
        observation_count=2,
        counts_by_kind={"data_quality_summary": 2},
        counts_by_severity={"info": 2},
        integrity_ok=True,
    )
    issues = compare_policy_regression_result(
        actual,
        PolicyRegressionExpected(
            observation_count=1,
            counts_by_kind={"data_quality_summary": 1},
            counts_by_severity={"info": 1},
        ),
    )
    codes = {item.code for item in issues}
    assert PolicyRegressionCode.OBSERVATION_COUNT_CHANGED.value in codes
    assert PolicyRegressionCode.OBSERVATION_KIND_COUNTS_CHANGED.value in codes
    assert PolicyRegressionCode.OBSERVATION_SEVERITY_COUNTS_CHANGED.value in codes


def test_forbidden_language_is_detected() -> None:
    issues = scan_policy_regression_payload(
        {
            "policy_name": "noop",
            "observations": [{"kind": "policy_note", "message": "buy this bar"}],
        }
    )
    assert any(
        item.code == PolicyRegressionCode.FORBIDDEN_OPERATIONAL_LANGUAGE.value
        for item in issues
    )


def test_report_hash_is_stable() -> None:
    path = default_policy_regression_matrix_path()
    first = run_policy_regression_matrix(path)
    second = run_policy_regression_matrix(path)
    assert first.ok is True
    assert first.report_hash == second.report_hash
    assert first.report_hash == hash_policy_regression_report(first)
    assert first.report_hash == hash_policy_regression_report(first.as_mapping())


def test_golden_matrix_passes() -> None:
    report = run_policy_regression_matrix(default_policy_regression_matrix_path())
    assert report.ok is True
    assert report.failed_count == 0
    assert report.error_count == 0
    warning_cases = {
        "noop-unknown-event",
        "event-counting-unknown-event",
        "data-quality-unknown-event",
        "coverage-gap-warning",
        "corporate-action-audit-unknown-event",
        "correction-audit-unknown-event",
    }
    found = {item.case_id for item in report.results if item.case_id in warning_cases}
    assert found == warning_cases
    for result in report.results:
        if result.case_id not in warning_cases:
            continue
        assert result.actual is not None
        assert result.actual.counts_by_severity.get("warning", 0) >= 1


def test_update_expected_writes_actuals_not_matrix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, research_settings: Settings
) -> None:
    shutil.copy(_FIXTURES / "simple_bars.jsonl", tmp_path / "simple_bars.jsonl")
    matrix_path = _write_matrix(
        tmp_path / "matrix.json",
        [
            _case_payload(
                case_id="noop-drift",
                expected_hash=_FAKE_HASH,
                expected_count=99,
            )
        ],
    )
    original = matrix_path.read_text(encoding="utf-8")
    output = tmp_path / "out"
    runner = _load_script("run-policy-regression-matrix.py")
    monkeypatch.setattr(runner, "get_settings", lambda: research_settings)
    with pytest.raises(SystemExit) as help_exc:
        runner.main(["--help"])
    assert help_exc.value.code == 0
    drifted = runner.main(["--matrix-path", str(matrix_path)])
    assert drifted == 1
    assert matrix_path.read_text(encoding="utf-8") == original
    updated = runner.main(
        [
            "--matrix-path",
            str(matrix_path),
            "--output-dir",
            str(output),
            "--update-expected",
        ]
    )
    assert updated == 0
    assert matrix_path.read_text(encoding="utf-8") == original
    actuals = json.loads((output / POLICY_REGRESSION_ACTUALS_ARTIFACT_NAME).read_text())
    assert actuals["kind"] == "policy_regression_actuals"
    assert actuals["cases"][0]["policy_output_hash"] != _FAKE_HASH
    assert (output / POLICY_REGRESSION_REPORT_ARTIFACT_NAME).is_file()
    written = write_policy_regression_artifacts(
        run_policy_regression_matrix(matrix_path),
        tmp_path / "second",
    )
    assert {item.path for item in written} == {
        POLICY_REGRESSION_REPORT_ARTIFACT_NAME,
        POLICY_REGRESSION_ACTUALS_ARTIFACT_NAME,
    }


def test_malformed_matrix_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "matrix.json"
    path.write_text('{"kind":"nope","format_version":1,"cases":[]}\n', encoding="utf-8")
    with pytest.raises(BacktestError) as exc:
        load_policy_regression_matrix(path)
    assert exc.value.code == BacktestErrorCode.CATALOG_INVALID


def test_no_trading_constructs() -> None:
    findings = detect_trading_constructs(event_kinds=tuple(EVENT_PRIORITY))
    assert findings == ()
    names = set(Base.metadata.tables)
    assert names.isdisjoint(FORBIDDEN_TABLE_NAMES)
    root = Path(__file__).resolve().parents[2] / "src" / "quant_platform"
    for package in FORBIDDEN_PACKAGE_NAMES:
        assert not (root / package).is_dir()
        assert not (root / f"{package}.py").is_file()
    text = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "quant_platform"
        / "backtest"
        / "policy_regression.py"
    ).read_text(encoding="utf-8")
    assert "class Strategy" not in text
    assert "class Signal" not in text
    case = PolicyRegressionCase(
        case_id="noop-simple-bars",
        description="NoOp over a tiny bar stream",
        fixture_path="simple_bars.jsonl",
        policy_name="noop",
        policy_config={},
        expected=PolicyRegressionExpected(),
    )
    result = run_policy_regression_case(
        case,
        fixture_root=_FIXTURES,
    )
    assert result.passed is True
    assert result.actual is not None
    assert "pnl" not in json.dumps(result.actual.as_mapping()).lower()
