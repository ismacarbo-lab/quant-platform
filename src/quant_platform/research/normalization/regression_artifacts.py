"""Local normalization-regression artifacts. Relative paths only; no trading."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from quant_platform.research.normalization.errors import (
    NormalizationError,
    NormalizationErrorCode,
)
from quant_platform.research.normalization.regression_types import (
    NORMALIZATION_REGRESSION_ACTUALS_ARTIFACT_NAME,
    NORMALIZATION_REGRESSION_ACTUALS_FORMAT_VERSION,
    NORMALIZATION_REGRESSION_ACTUALS_KIND,
    NORMALIZATION_REGRESSION_REPORT_ARTIFACT_NAME,
    NormalizationRegressionActual,
    NormalizationRegressionArtifact,
    NormalizationRegressionMatrixReport,
    NormalizationRegressionResult,
    default_normalization_regression_artifacts,
)
from quant_platform.research.snapshots import manifest_contains_secrets
from quant_platform.simulation.run_types import artifact_path_is_unsafe


def write_normalization_regression_artifacts(
    report: NormalizationRegressionMatrixReport,
    output_dir: Path | str,
    *,
    write_actuals: bool = True,
) -> tuple[NormalizationRegressionArtifact, ...]:
    """Write regression report JSON and optional actuals for human review."""
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    written: list[NormalizationRegressionArtifact] = []
    report_artifact = NormalizationRegressionArtifact(
        name="report",
        path=NORMALIZATION_REGRESSION_REPORT_ARTIFACT_NAME,
    )
    _write_json(report.as_mapping(), target / report_artifact.path)
    written.append(report_artifact)
    if write_actuals:
        actuals_artifact = NormalizationRegressionArtifact(
            name="actuals",
            path=NORMALIZATION_REGRESSION_ACTUALS_ARTIFACT_NAME,
        )
        _write_json(
            normalization_regression_actuals_mapping(report.results),
            target / actuals_artifact.path,
        )
        written.append(actuals_artifact)
    expected = {
        item.name: item.path for item in default_normalization_regression_artifacts()
    }
    for item in written:
        if expected.get(item.name) != item.path:
            raise NormalizationError(
                "normalization regression artifact names must stay relative",
                code=NormalizationErrorCode.ARTIFACT_INVALID,
            )
    return tuple(written)


def normalization_regression_actuals_mapping(
    results: Sequence[NormalizationRegressionResult],
) -> dict[str, object]:
    """JSON object humans copy into expected.json after reviewing hash drift."""
    cases: list[dict[str, object]] = []
    for result in sorted(results, key=lambda item: item.case_id):
        actual = result.actual
        if actual is None:
            cases.append(
                {
                    "case_id": result.case_id,
                    "fixture_dir": result.fixture_dir,
                    "adjustment_mode": result.adjustment_mode,
                    "passed": result.passed,
                    "expected_dataset_hash": None,
                    "expected_bar_count": None,
                    "expected_issue_count": None,
                    "expected_adjusted_bar_count": None,
                    "expected_actions_applied": None,
                    "expected_warnings": None,
                }
            )
            continue
        cases.append(_actuals_case_mapping(actual, result.fixture_dir, result.passed))
    return {
        "kind": NORMALIZATION_REGRESSION_ACTUALS_KIND,
        "format_version": NORMALIZATION_REGRESSION_ACTUALS_FORMAT_VERSION,
        "note": (
            "Copy hashes and counts into each case expected.json by hand after "
            "review. The runner does not rewrite golden expected values."
        ),
        "cases": cases,
    }


def _actuals_case_mapping(
    actual: NormalizationRegressionActual,
    fixture_dir: str,
    passed: bool,
) -> dict[str, object]:
    return {
        "case_id": actual.case_id,
        "fixture_dir": fixture_dir,
        "adjustment_mode": actual.adjustment_mode,
        "passed": passed,
        "expected_dataset_hash": actual.dataset_hash,
        "expected_bar_count": actual.bar_count,
        "expected_issue_count": actual.issue_count,
        "expected_adjusted_bar_count": actual.adjusted_bar_count,
        "expected_actions_applied": actual.actions_applied,
        "expected_warnings": list(actual.warnings),
        "raw_dataset_hash": actual.raw_dataset_hash,
    }


def _write_json(payload: Mapping[str, object], path: Path) -> None:
    if artifact_path_is_unsafe(path.name):
        raise NormalizationError(
            "normalization regression artifact paths must be relative",
            code=NormalizationErrorCode.ARTIFACT_INVALID,
        )
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    if manifest_contains_secrets(text):
        raise NormalizationError(
            "normalization regression artifacts must not contain secrets",
            code=NormalizationErrorCode.SECRET_LIKE_VALUE,
        )
    path.write_text(text, encoding="utf-8")
