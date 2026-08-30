"""Corporate-action normalization regression without Docker. No trading."""

from __future__ import annotations

import importlib.util
import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from quant_platform.core.config import Settings
from quant_platform.research.normalization.regression import (
    compare_normalization_regression_result,
    default_normalization_regression_dir,
    hash_normalization_regression_report,
    load_normalization_regression_case,
    run_normalization_regression_case,
    run_normalization_regression_matrix,
    scan_normalization_regression_text,
)
from quant_platform.research.normalization.regression_artifacts import (
    write_normalization_regression_artifacts,
)
from quant_platform.research.normalization.regression_types import (
    NORMALIZATION_REGRESSION_ACTUALS_ARTIFACT_NAME,
    NORMALIZATION_REGRESSION_REPORT_ARTIFACT_NAME,
    NormalizationRegressionActual,
    NormalizationRegressionCode,
    NormalizationRegressionExpected,
)
from quant_platform.simulation.constructs import detect_trading_constructs

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
_FIXTURES = (
    Path(__file__).resolve().parents[1] / "fixtures" / "normalization_regression"
)
_FAKE_HASH = "sha256:" + ("a" * 64)
_FORBIDDEN_METRIC_TOKENS = (
    "sharpe",
    "drawdown",
    "hit_ratio",
    "pnl",
    "returns",
)


def _load_script(filename: str):
    path = _SCRIPTS / filename
    spec = importlib.util.spec_from_file_location(filename.replace("-", "_"), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _copy_case(tmp_path: Path, name: str) -> Path:
    dest = tmp_path / name
    shutil.copytree(_FIXTURES / name, dest)
    return dest


def test_golden_fixtures_load() -> None:
    root = default_normalization_regression_dir()
    names = sorted(item.name for item in root.iterdir() if item.is_dir())
    assert names == [
        "dividend_informational",
        "future_action_not_visible",
        "multiple_actions_compounded",
        "reverse_split_1_for_4",
        "split_2_for_1",
        "split_4_for_1",
    ]
    for name in names:
        case = load_normalization_regression_case(root / name)
        assert case.case_id == name
        assert case.expected.dataset_hash
        assert case.expected.dataset_hash.startswith("sha256:")


def test_split_case_produces_expected_hash() -> None:
    root = default_normalization_regression_dir()
    case = load_normalization_regression_case(root / "split_2_for_1")
    result = run_normalization_regression_case(case, fixtures_root=root)
    assert result.passed is True
    assert result.actual is not None
    assert result.actual.dataset_hash == case.expected.dataset_hash
    assert result.actual.adjusted_bar_count == 1
    assert result.actual.actions_applied == 1


def test_split_4_for_1_produces_expected_hash() -> None:
    root = default_normalization_regression_dir()
    case = load_normalization_regression_case(root / "split_4_for_1")
    result = run_normalization_regression_case(case, fixtures_root=root)
    assert result.passed is True
    assert result.actual is not None
    assert result.actual.dataset_hash == case.expected.dataset_hash


def test_reverse_split_case_produces_expected_hash() -> None:
    root = default_normalization_regression_dir()
    case = load_normalization_regression_case(root / "reverse_split_1_for_4")
    result = run_normalization_regression_case(case, fixtures_root=root)
    assert result.passed is True
    assert result.actual is not None
    assert result.actual.dataset_hash == case.expected.dataset_hash
    assert result.actual.adjusted_bar_count == 1


def test_dividend_case_produces_warning() -> None:
    root = default_normalization_regression_dir()
    case = load_normalization_regression_case(root / "dividend_informational")
    result = run_normalization_regression_case(case, fixtures_root=root)
    assert result.passed is True
    assert result.actual is not None
    assert result.actual.warnings == ("dividend_not_adjusted",)
    assert result.actual.actions_applied == 0
    assert result.actual.adjusted_bar_count == 0


def test_future_action_not_visible() -> None:
    root = default_normalization_regression_dir()
    case = load_normalization_regression_case(root / "future_action_not_visible")
    result = run_normalization_regression_case(case, fixtures_root=root)
    assert result.passed is True
    assert result.actual is not None
    assert result.actual.actions_applied == 0
    assert result.actual.adjusted_bar_count == 0
    assert result.actual.warnings == ()


def test_multiple_actions_compounded_stable() -> None:
    root = default_normalization_regression_dir()
    case = load_normalization_regression_case(root / "multiple_actions_compounded")
    first = run_normalization_regression_case(case, fixtures_root=root)
    second = run_normalization_regression_case(case, fixtures_root=root)
    assert first.passed is True
    assert first.actual is not None
    assert second.actual is not None
    assert first.actual.dataset_hash == second.actual.dataset_hash
    assert first.actual.actions_applied == 2
    assert first.actual.dataset_hash == case.expected.dataset_hash


def test_regression_detects_hash_drift() -> None:
    actual = NormalizationRegressionActual(
        case_id="drift",
        adjustment_mode="split_only",
        as_of=None,
        dataset_hash=_FAKE_HASH,
        bar_count=1,
        issue_count=0,
        adjusted_bar_count=1,
        actions_applied=1,
        warnings=(),
    )
    expected = NormalizationRegressionExpected(
        dataset_hash="sha256:" + ("b" * 64),
        bar_count=1,
        issue_count=0,
        adjusted_bar_count=1,
        actions_applied=1,
        warnings=(),
    )
    issues = compare_normalization_regression_result(actual, expected)
    assert [item.code for item in issues] == [
        NormalizationRegressionCode.DATASET_HASH_CHANGED.value
    ]


def test_regression_detects_count_drift() -> None:
    actual = NormalizationRegressionActual(
        case_id="count",
        adjustment_mode="split_only",
        as_of=None,
        dataset_hash=_FAKE_HASH,
        bar_count=2,
        issue_count=1,
        adjusted_bar_count=0,
        actions_applied=0,
        warnings=("dividend_not_adjusted",),
    )
    expected = NormalizationRegressionExpected(
        dataset_hash=_FAKE_HASH,
        bar_count=1,
        issue_count=0,
        adjusted_bar_count=1,
        actions_applied=1,
        warnings=(),
    )
    codes = {
        item.code for item in compare_normalization_regression_result(actual, expected)
    }
    assert NormalizationRegressionCode.BAR_COUNT_CHANGED.value in codes
    assert NormalizationRegressionCode.ISSUE_COUNT_CHANGED.value in codes
    assert NormalizationRegressionCode.ADJUSTED_BAR_COUNT_CHANGED.value in codes
    assert NormalizationRegressionCode.ACTIONS_APPLIED_CHANGED.value in codes
    assert NormalizationRegressionCode.WARNING_COUNT_CHANGED.value in codes


def test_missing_fixture_fails(tmp_path: Path) -> None:
    case_dir = tmp_path / "missing_case"
    case_dir.mkdir()
    (case_dir / "request.json").write_text(
        json.dumps(
            {
                "as_of": "2024-01-20T00:00:00+00:00",
                "start_time": "2024-01-01T00:00:00+00:00",
                "end_time": "2024-01-05T00:00:00+00:00",
                "source_name": "local_csv",
                "adjustment_mode": "split_only",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    report = run_normalization_regression_matrix(tmp_path)
    assert report.ok is False
    codes = [issue.code for issue in report.results[0].issues]
    assert NormalizationRegressionCode.MISSING_FIXTURE.value in codes


def test_invalid_request_fails(tmp_path: Path) -> None:
    dest = _copy_case(tmp_path, "split_2_for_1")
    request = json.loads((dest / "request.json").read_text(encoding="utf-8"))
    request["adjustment_mode"] = "not_a_mode"
    (dest / "request.json").write_text(
        json.dumps(request, indent=2) + "\n", encoding="utf-8"
    )
    case = load_normalization_regression_case(dest)
    result = run_normalization_regression_case(case, fixtures_root=tmp_path)
    assert result.passed is False
    codes = [issue.code for issue in result.issues]
    assert NormalizationRegressionCode.INVALID_REQUEST.value in codes


def test_report_hash_is_stable() -> None:
    first = run_normalization_regression_matrix()
    second = run_normalization_regression_matrix()
    assert first.ok is True
    assert first.case_count == 6
    assert first.report_hash == second.report_hash
    assert first.report_hash == hash_normalization_regression_report(first)
    assert first.report_hash == hash_normalization_regression_report(first.as_mapping())
    assert first.report_hash.startswith("sha256:")


def test_script_json_valid(
    monkeypatch: pytest.MonkeyPatch,
    research_settings: Settings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runner = _load_script("run-normalization-regression.py")
    monkeypatch.setattr(runner, "get_settings", lambda: research_settings)
    code = runner.main(["--json"])
    captured = capsys.readouterr()
    assert code == 0
    payload = json.loads(captured.out)
    assert payload["kind"] == "normalization_regression_matrix_report"
    assert payload["ok"] is True
    assert payload["case_count"] == 6
    blob = captured.out + captured.err
    assert "DATABASE_URL" not in blob
    assert "postgresql+psycopg://" not in blob


def test_update_expected_writes_actuals_not_goldens(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    research_settings: Settings,
) -> None:
    runner = _load_script("run-normalization-regression.py")
    monkeypatch.setattr(runner, "get_settings", lambda: research_settings)
    output = tmp_path / "out"
    before = {
        name: (path.read_text(encoding="utf-8"))
        for name in (
            "split_2_for_1",
            "dividend_informational",
        )
        for path in [_FIXTURES / name / "expected.json"]
    }
    code = runner.main(
        [
            "--fixtures-dir",
            str(_FIXTURES),
            "--output-dir",
            str(output),
            "--update-expected",
        ]
    )
    assert code == 0
    assert (output / NORMALIZATION_REGRESSION_REPORT_ARTIFACT_NAME).is_file()
    actuals = json.loads(
        (output / NORMALIZATION_REGRESSION_ACTUALS_ARTIFACT_NAME).read_text(
            encoding="utf-8"
        )
    )
    assert actuals["kind"] == "normalization_regression_actuals"
    assert "does not rewrite golden" in actuals["note"]
    for name, text in before.items():
        assert (_FIXTURES / name / "expected.json").read_text(encoding="utf-8") == text


def test_write_artifacts_use_relative_paths(tmp_path: Path) -> None:
    report = run_normalization_regression_matrix()
    written = write_normalization_regression_artifacts(report, tmp_path)
    paths = {item.path for item in written}
    assert paths == {
        NORMALIZATION_REGRESSION_REPORT_ARTIFACT_NAME,
        NORMALIZATION_REGRESSION_ACTUALS_ARTIFACT_NAME,
    }
    for item in written:
        assert "/" not in item.path
        assert not item.path.startswith("/")


def test_no_forbidden_metric_terms() -> None:
    report = run_normalization_regression_matrix()
    blob = json.dumps(report.as_mapping(), sort_keys=True)
    lowered = blob.lower()
    for token in _FORBIDDEN_METRIC_TOKENS:
        assert token not in lowered
    issues = scan_normalization_regression_text('{"metric":"sharpe"}')
    assert [item.code for item in issues] == [
        NormalizationRegressionCode.FORBIDDEN_METRIC_DETECTED.value
    ]


def test_no_trading_constructs_in_normalization_package() -> None:
    findings = detect_trading_constructs()
    assert findings == ()
    root = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "quant_platform"
        / "research"
        / "normalization"
    )
    for filename in (
        "regression.py",
        "regression_types.py",
        "regression_artifacts.py",
    ):
        text = (root / filename).read_text(encoding="utf-8")
        assert "class Strategy" not in text
        assert "class Signal" not in text
        assert "class Order" not in text
        assert "class Portfolio" not in text
        assert "class Broker" not in text


def test_hash_drift_on_copied_case(tmp_path: Path) -> None:
    dest = _copy_case(tmp_path, "split_2_for_1")
    expected = json.loads((dest / "expected.json").read_text(encoding="utf-8"))
    expected["expected_dataset_hash"] = _FAKE_HASH
    (dest / "expected.json").write_text(
        json.dumps(expected, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    case = load_normalization_regression_case(dest)
    result = run_normalization_regression_case(case, fixtures_root=tmp_path)
    assert result.passed is False
    codes = [issue.code for issue in result.issues]
    assert NormalizationRegressionCode.DATASET_HASH_CHANGED.value in codes


def test_report_hash_changes_when_result_changes() -> None:
    report = run_normalization_regression_matrix()
    drifted = replace(
        report.results[0],
        passed=False,
        issues=report.results[0].issues,
    )
    mutated = replace(report, results=(drifted, *report.results[1:]), ok=False)
    assert hash_normalization_regression_report(mutated) != report.report_hash
