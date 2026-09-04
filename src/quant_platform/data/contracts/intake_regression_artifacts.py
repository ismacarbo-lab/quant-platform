"""Local contract-payload intake regression artifacts. Relative paths only."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from quant_platform.data.contracts.errors import (
    VendorContractError,
    VendorContractErrorCode,
)
from quant_platform.data.contracts.intake_regression_types import (
    INTAKE_REGRESSION_ACTUALS_ARTIFACT_NAME,
    INTAKE_REGRESSION_ACTUALS_FORMAT_VERSION,
    INTAKE_REGRESSION_ACTUALS_KIND,
    INTAKE_REGRESSION_REPORT_ARTIFACT_NAME,
    IntakeRegressionArtifact,
    IntakeRegressionMatrixReport,
    IntakeRegressionResult,
    default_intake_regression_artifacts,
)
from quant_platform.simulation.run_types import artifact_path_is_unsafe

_SECRET_MARKERS = (
    "DATABASE_URL",
    "POSTGRES_PASSWORD",
    "postgresql://",
    "postgres://",
    "postgresql+psycopg://",
)


def write_intake_regression_artifacts(
    report: IntakeRegressionMatrixReport,
    output_dir: Path | str,
    *,
    write_actuals: bool = True,
) -> tuple[IntakeRegressionArtifact, ...]:
    """Write regression report JSON and optional actuals for human review."""
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    written: list[IntakeRegressionArtifact] = []
    report_artifact = IntakeRegressionArtifact(
        name="report",
        path=INTAKE_REGRESSION_REPORT_ARTIFACT_NAME,
    )
    _write_json(report.as_mapping(), target / report_artifact.path)
    written.append(report_artifact)
    if write_actuals:
        actuals_artifact = IntakeRegressionArtifact(
            name="actuals",
            path=INTAKE_REGRESSION_ACTUALS_ARTIFACT_NAME,
        )
        _write_json(
            intake_regression_actuals_mapping(report.results),
            target / actuals_artifact.path,
        )
        written.append(actuals_artifact)
    expected = {item.name: item.path for item in default_intake_regression_artifacts()}
    for item in written:
        if expected.get(item.name) != item.path:
            raise VendorContractError(
                "intake regression artifact names must stay relative",
                code=VendorContractErrorCode.VALIDATION_ERROR,
            )
    return tuple(written)


def intake_regression_actuals_mapping(
    results: Sequence[IntakeRegressionResult],
) -> dict[str, object]:
    """JSON object humans copy into expected.json after reviewing hash drift."""
    cases: list[dict[str, object]] = []
    for result in sorted(results, key=lambda item: item.case_id):
        actual = result.actual
        if actual is None:
            continue
        cases.append(
            {
                "case_id": actual.case_id,
                "expected_ok": actual.ok,
                "expected_write_db": actual.write_db,
                "expected_allow_invalid": actual.allow_invalid,
                "expected_issue_count": actual.issue_count,
                "expected_issue_codes": list(actual.issue_codes),
                "expected_intake_hash": actual.intake_hash,
                "expected_batch_hash": actual.batch_hash,
                "expected_conformance_hash": actual.conformance_hash,
                "expected_planned_daily_bar_count": actual.planned_daily_bar_count,
                "expected_planned_corporate_action_count": (
                    actual.planned_corporate_action_count
                ),
                "expected_planned_market_session_count": (
                    actual.planned_market_session_count
                ),
            }
        )
    return {
        "kind": INTAKE_REGRESSION_ACTUALS_KIND,
        "format_version": INTAKE_REGRESSION_ACTUALS_FORMAT_VERSION,
        "cases": cases,
    }


def _write_json(payload: Mapping[str, object], path: Path) -> None:
    if artifact_path_is_unsafe(path.name):
        raise VendorContractError(
            "intake regression artifact paths must be relative",
            code=VendorContractErrorCode.VALIDATION_ERROR,
        )
    text = json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    lowered = text.lower()
    for marker in _SECRET_MARKERS:
        if marker.lower() in lowered:
            raise VendorContractError(
                "intake regression artifacts must not contain secrets",
                code=VendorContractErrorCode.SECRET_IN_METADATA,
            )
    path.write_text(text, encoding="utf-8")
