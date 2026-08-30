"""Local normalized-dataset artifacts. Relative paths only; no secrets."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from quant_platform import __version__
from quant_platform.core.time import utc_now
from quant_platform.research.normalization.errors import (
    NormalizationError,
    NormalizationErrorCode,
)
from quant_platform.research.normalization.types import (
    BARS_ARTIFACT_NAME,
    MANIFEST_ARTIFACT_NAME,
    NORMALIZED_DAILY_BAR_COLUMNS,
    REPORT_ARTIFACT_NAME,
    NormalizationArtifact,
    NormalizationManifest,
    NormalizedDailyBarsDataset,
)
from quant_platform.research.snapshots import (
    canonical_datetime,
    canonical_json,
    get_git_commit,
    manifest_contains_secrets,
)
from quant_platform.simulation.run_types import artifact_path_is_unsafe

NORMALIZATION_MANIFEST_KIND = "normalized_daily_bars_manifest"
NORMALIZATION_MANIFEST_FORMAT_VERSION = 1


def default_normalization_artifacts() -> tuple[NormalizationArtifact, ...]:
    return (
        NormalizationArtifact(
            name="normalized_daily_bars", path=BARS_ARTIFACT_NAME, kind="csv"
        ),
        NormalizationArtifact(
            name="normalization_report", path=REPORT_ARTIFACT_NAME, kind="json"
        ),
        NormalizationArtifact(
            name="normalization_manifest", path=MANIFEST_ARTIFACT_NAME, kind="json"
        ),
    )


def write_normalized_dataset_artifacts(
    dataset: NormalizedDailyBarsDataset,
    output_dir: Path | str,
) -> NormalizationManifest:
    """Write CSV, report, and manifest. Does not mutate PostgreSQL."""
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    artifacts = default_normalization_artifacts()
    for item in artifacts:
        if artifact_path_is_unsafe(item.path):
            raise NormalizationError(
                "normalization artifact paths must be relative",
                code=NormalizationErrorCode.ARTIFACT_INVALID,
            )
    bars_path = root / BARS_ARTIFACT_NAME
    report_path = root / REPORT_ARTIFACT_NAME
    manifest_path = root / MANIFEST_ARTIFACT_NAME
    _write_csv(dataset, bars_path)
    report_payload = _jsonable(dataset.report.as_mapping())
    _write_json(report_payload, report_path)
    summary: tuple[dict[str, object], ...] = tuple(
        {
            "action_id": None if item.action_id is None else str(item.action_id),
            "action_type": item.action_type,
            "instrument_id": str(item.instrument_id),
            "applied": item.applied,
        }
        for item in dataset.report.applied_actions
    )
    manifest = NormalizationManifest(
        kind=NORMALIZATION_MANIFEST_KIND,
        format_version=NORMALIZATION_MANIFEST_FORMAT_VERSION,
        as_of=dataset.request.as_of,
        adjustment_mode=dataset.request.adjustment_mode.value,
        source_name=dataset.request.source_name,
        dataset_hash=dataset.dataset_hash,
        raw_dataset_hash=dataset.raw_dataset_hash,
        bar_count=len(dataset.rows),
        applied_action_count=dataset.report.applied_action_count,
        issue_count=dataset.report.issue_count,
        warning_count=dataset.report.warning_count,
        error_count=dataset.report.error_count,
        artifacts=artifacts,
        applied_actions_summary=summary,
        package_version=__version__,
        git_commit=get_git_commit(),
        created_at=utc_now(),
    )
    manifest_payload = _jsonable(manifest.as_mapping())
    blob = canonical_json(manifest_payload)
    if manifest_contains_secrets(blob):
        raise NormalizationError(
            "normalization artifacts must not contain secrets",
            code=NormalizationErrorCode.SECRET_LIKE_VALUE,
        )
    _write_json(manifest_payload, manifest_path)
    return manifest


def _write_csv(dataset: NormalizedDailyBarsDataset, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(NORMALIZED_DAILY_BAR_COLUMNS), extrasaction="ignore"
        )
        writer.writeheader()
        for row in dataset.rows:
            writer.writerow(row.as_csv_row())


def _write_json(payload: object, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    if manifest_contains_secrets(text):
        raise NormalizationError(
            "normalization artifacts must not contain secrets",
            code=NormalizationErrorCode.SECRET_LIKE_VALUE,
        )
    path.write_text(text, encoding="utf-8")


def _jsonable(value: object) -> object:
    from datetime import datetime
    from decimal import Decimal
    from uuid import UUID

    if isinstance(value, datetime):
        return canonical_datetime(value)
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value
