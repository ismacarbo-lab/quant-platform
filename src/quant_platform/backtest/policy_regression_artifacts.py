"""Local policy-regression artifacts. Relative paths only; no trading."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from quant_platform.backtest.errors import BacktestError, BacktestErrorCode
from quant_platform.backtest.policy_regression_types import (
    POLICY_REGRESSION_ACTUALS_ARTIFACT_NAME,
    POLICY_REGRESSION_ACTUALS_FORMAT_VERSION,
    POLICY_REGRESSION_ACTUALS_KIND,
    POLICY_REGRESSION_REPORT_ARTIFACT_NAME,
    PolicyRegressionActual,
    PolicyRegressionArtifact,
    PolicyRegressionMatrixReport,
    PolicyRegressionResult,
    default_policy_regression_artifacts,
)
from quant_platform.research.snapshots import manifest_contains_secrets
from quant_platform.simulation.run_types import artifact_path_is_unsafe


def write_policy_regression_artifacts(
    report: PolicyRegressionMatrixReport,
    output_dir: Path | str,
    *,
    write_actuals: bool = True,
) -> tuple[PolicyRegressionArtifact, ...]:
    """Write regression report JSON and optional actuals for human review."""
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    written: list[PolicyRegressionArtifact] = []
    report_artifact = PolicyRegressionArtifact(
        name="report",
        path=POLICY_REGRESSION_REPORT_ARTIFACT_NAME,
    )
    _write_json(report.as_mapping(), target / report_artifact.path)
    written.append(report_artifact)
    if write_actuals:
        actuals_artifact = PolicyRegressionArtifact(
            name="actuals",
            path=POLICY_REGRESSION_ACTUALS_ARTIFACT_NAME,
        )
        _write_json(
            policy_regression_actuals_mapping(report.results),
            target / actuals_artifact.path,
        )
        written.append(actuals_artifact)
    expected = {item.name: item.path for item in default_policy_regression_artifacts()}
    for item in written:
        if expected.get(item.name) != item.path:
            raise BacktestError(
                "policy regression artifact names must stay relative",
                code=BacktestErrorCode.CATALOG_INVALID,
            )
    return tuple(written)


def policy_regression_actuals_mapping(
    results: Sequence[PolicyRegressionResult],
) -> dict[str, object]:
    """JSON object humans copy into matrix.json after reviewing hash drift."""
    cases: list[dict[str, object]] = []
    for result in sorted(results, key=lambda item: item.case_id):
        actual = result.actual
        if actual is None:
            cases.append(
                {
                    "case_id": result.case_id,
                    "policy_name": result.policy_name,
                    "fixture_path": result.fixture_path,
                    "passed": result.passed,
                    "policy_output_hash": None,
                    "observation_count": None,
                    "counts_by_kind": None,
                    "counts_by_severity": None,
                    "integrity_ok": None,
                }
            )
            continue
        cases.append(_actuals_case_mapping(actual, result.fixture_path, result.passed))
    return {
        "kind": POLICY_REGRESSION_ACTUALS_KIND,
        "format_version": POLICY_REGRESSION_ACTUALS_FORMAT_VERSION,
        "note": (
            "Copy hashes and counts into matrix.json by hand after review. "
            "The runner does not rewrite golden expected values."
        ),
        "cases": cases,
    }


def _actuals_case_mapping(
    actual: PolicyRegressionActual,
    fixture_path: str,
    passed: bool,
) -> dict[str, object]:
    return {
        "case_id": actual.case_id,
        "policy_name": actual.policy_name,
        "fixture_path": fixture_path,
        "passed": passed,
        "policy_output_hash": actual.policy_output_hash,
        "observation_count": actual.observation_count,
        "counts_by_kind": dict(sorted(actual.counts_by_kind.items())),
        "counts_by_severity": dict(sorted(actual.counts_by_severity.items())),
        "integrity_ok": actual.integrity_ok,
        "policy_config": dict(actual.policy_config),
    }


def _write_json(payload: Mapping[str, object], path: Path) -> None:
    if artifact_path_is_unsafe(path.name):
        raise BacktestError(
            "policy regression artifact paths must be relative",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    if manifest_contains_secrets(text):
        raise BacktestError(
            "policy regression artifacts must not contain secrets",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    path.write_text(text, encoding="utf-8")
