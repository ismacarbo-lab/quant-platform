"""Local data-contract conformance regression artifacts. Relative paths only."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from quant_platform.data.contracts.conformance_regression_types import (
    CONFORMANCE_REGRESSION_ACTUALS_ARTIFACT_NAME,
    CONFORMANCE_REGRESSION_ACTUALS_FORMAT_VERSION,
    CONFORMANCE_REGRESSION_ACTUALS_KIND,
    CONFORMANCE_REGRESSION_REPORT_ARTIFACT_NAME,
    ConformanceRegressionActual,
    ConformanceRegressionArtifact,
    ConformanceRegressionMatrixReport,
    ConformanceRegressionResult,
    default_conformance_regression_artifacts,
)
from quant_platform.data.contracts.errors import (
    VendorContractError,
    VendorContractErrorCode,
)
from quant_platform.simulation.run_types import artifact_path_is_unsafe

_SECRET_MARKERS = (
    "DATABASE_URL",
    "POSTGRES_PASSWORD",
    "postgresql://",
    "postgres://",
    "postgresql+psycopg://",
)


def write_conformance_regression_artifacts(
    report: ConformanceRegressionMatrixReport,
    output_dir: Path | str,
    *,
    write_actuals: bool = True,
) -> tuple[ConformanceRegressionArtifact, ...]:
    """Write regression report JSON and optional actuals for human review."""
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    written: list[ConformanceRegressionArtifact] = []
    report_artifact = ConformanceRegressionArtifact(
        name="report",
        path=CONFORMANCE_REGRESSION_REPORT_ARTIFACT_NAME,
    )
    _write_json(report.as_mapping(), target / report_artifact.path)
    written.append(report_artifact)
    if write_actuals:
        actuals_artifact = ConformanceRegressionArtifact(
            name="actuals",
            path=CONFORMANCE_REGRESSION_ACTUALS_ARTIFACT_NAME,
        )
        _write_json(
            conformance_regression_actuals_mapping(report.results),
            target / actuals_artifact.path,
        )
        written.append(actuals_artifact)
    expected = {
        item.name: item.path for item in default_conformance_regression_artifacts()
    }
    for item in written:
        if expected.get(item.name) != item.path:
            raise VendorContractError(
                "conformance regression artifact names must stay relative",
                code=VendorContractErrorCode.VALIDATION_ERROR,
            )
    return tuple(written)


def conformance_regression_actuals_mapping(
    results: Sequence[ConformanceRegressionResult],
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
                    "passed": result.passed,
                    "expected_conformance_hash": None,
                    "expected_batch_hash": None,
                    "expected_issue_count": None,
                    "expected_issue_codes": None,
                    "expected_validation_ok": None,
                    "expected_forbidden_terms_ok": None,
                    "expected_offline_only_ok": None,
                    "expected_ok": None,
                }
            )
            continue
        cases.append(_actuals_case_mapping(actual, result.fixture_dir, result.passed))
    return {
        "kind": CONFORMANCE_REGRESSION_ACTUALS_KIND,
        "format_version": CONFORMANCE_REGRESSION_ACTUALS_FORMAT_VERSION,
        "note": (
            "Copy hashes and counts into each case expected.json by hand after "
            "review. The runner does not rewrite golden expected values."
        ),
        "cases": cases,
    }


def _actuals_case_mapping(
    actual: ConformanceRegressionActual,
    fixture_dir: str,
    passed: bool,
) -> dict[str, object]:
    return {
        "case_id": actual.case_id,
        "fixture_dir": fixture_dir,
        "passed": passed,
        "expected_conformance_hash": actual.conformance_hash,
        "expected_batch_hash": actual.batch_hash,
        "expected_issue_count": actual.issue_count,
        "expected_issue_codes": list(actual.issue_codes),
        "expected_validation_ok": actual.validation_ok,
        "expected_forbidden_terms_ok": actual.forbidden_terms_ok,
        "expected_offline_only_ok": actual.offline_only_ok,
        "expected_ok": actual.ok,
    }


def _write_json(payload: Mapping[str, object], path: Path) -> None:
    if artifact_path_is_unsafe(path.name):
        raise VendorContractError(
            "conformance regression artifact paths must be relative",
            code=VendorContractErrorCode.VALIDATION_ERROR,
        )
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    lowered = text.lower()
    for marker in _SECRET_MARKERS:
        if marker.lower() in lowered:
            raise VendorContractError(
                "conformance regression artifacts must not contain secrets",
                code=VendorContractErrorCode.SECRET_IN_METADATA,
            )
    path.write_text(text, encoding="utf-8")
