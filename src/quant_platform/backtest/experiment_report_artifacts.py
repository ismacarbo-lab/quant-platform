"""Local experiment research-report artifacts. Metadata only; no event copies."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from quant_platform.backtest.errors import BacktestError, BacktestErrorCode
from quant_platform.backtest.experiment_readiness_types import (
    BacktestExperimentResearchReport,
    BacktestExperimentUsabilityReport,
)
from quant_platform.backtest.experiment_types import (
    EXPERIMENT_RESEARCH_REPORT_ARTIFACT_NAME,
    EXPERIMENT_USABILITY_ARTIFACT_NAME,
)
from quant_platform.research.snapshots import manifest_contains_secrets
from quant_platform.simulation.run_types import artifact_path_is_unsafe


def write_backtest_experiment_report_artifacts(
    report: BacktestExperimentResearchReport,
    output_dir: Path | str,
    *,
    usability: BacktestExperimentUsabilityReport | None = None,
) -> Path:
    """Write experiment_research_report.json and optional usability JSON."""
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    report_path = target / EXPERIMENT_RESEARCH_REPORT_ARTIFACT_NAME
    _write_json(report.as_mapping(), report_path)
    if usability is not None:
        payload = dict(usability.as_mapping())
        payload.pop("experiment_root", None)
        _write_json(payload, target / EXPERIMENT_USABILITY_ARTIFACT_NAME)
    return target


def _write_json(payload: Mapping[str, object], path: Path) -> None:
    if artifact_path_is_unsafe(path.name):
        raise BacktestError(
            "experiment report paths must be relative",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    if manifest_contains_secrets(text):
        raise BacktestError(
            "experiment report must not contain secrets",
            code=BacktestErrorCode.CATALOG_INVALID,
        )
    path.write_text(text, encoding="utf-8")
