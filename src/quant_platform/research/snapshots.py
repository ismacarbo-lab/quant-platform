"""Local reproducible dataset snapshots. No cloud, vendors, or trading."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from quant_platform import __version__
from quant_platform.core.time import utc_now
from quant_platform.research.datasets import get_daily_bars_dataset
from quant_platform.research.errors import DatasetErrorCode, DatasetValidationError
from quant_platform.research.export import write_daily_bars_csv
from quant_platform.research.quality import (
    get_dataset_quality_report,
    write_dataset_quality_json,
)
from quant_platform.research.quality_types import (
    DatasetQualityReport,
    build_dataset_quality_request,
)
from quant_platform.research.snapshot_types import (
    DAILY_BARS_ARTIFACT_NAME,
    MANIFEST_ARTIFACT_NAME,
    QUALITY_ARTIFACT_NAME,
    DatasetSnapshotManifest,
    DatasetSnapshotRequest,
    DatasetSnapshotResult,
    SnapshotArtifact,
    build_dataset_snapshot_request,
)
from quant_platform.research.types import (
    DAILY_BAR_DATASET_COLUMNS,
    DailyBarDatasetRow,
    DailyBarsDataset,
    DailyBarsDatasetRequest,
)

_DECIMAL_QUANT = Decimal("0.00000001")
_ACCIDENTAL_GIT_ROOT = Path("/home/isma")
_SECRET_MARKERS = (
    "DATABASE_URL",
    "POSTGRES_PASSWORD",
    "postgresql://",
    "postgres://",
    "postgresql+psycopg://",
)

DATASET_HASH_KIND = "daily_bars_dataset"
QUALITY_HASH_KIND = "dataset_quality_report"
HASH_FORMAT_VERSION = 1
SHA256_HASH_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


def is_sha256_digest(value: str) -> bool:
    return bool(SHA256_HASH_PATTERN.fullmatch(value))


def canonical_datetime(value: datetime) -> str:
    """UTC timestamp with microseconds and a trailing Z."""
    if value.tzinfo is None:
        raise DatasetValidationError(
            "snapshot timestamps must be timezone-aware UTC",
            code=DatasetErrorCode.NAIVE_TIMESTAMP,
        )
    utc = value.astimezone(UTC)
    return utc.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def canonical_decimal(value: Decimal | None) -> str:
    """Fixed 8-decimal-place string; None becomes empty."""
    if value is None:
        return ""
    quantized = value.quantize(_DECIMAL_QUANT, rounding=ROUND_HALF_EVEN)
    return format(quantized, "f")


def canonical_json(value: object) -> str:
    """Stable JSON: sorted keys, compact separators, ASCII."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def sha256_canonical(value: object) -> str:
    digest = hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def dataset_request_mapping(request: DailyBarsDatasetRequest) -> dict[str, object]:
    return {
        "as_of": canonical_datetime(request.as_of),
        "start_time": canonical_datetime(request.start_time),
        "end_time": canonical_datetime(request.end_time),
        "symbols": list(request.symbols) if request.symbols is not None else None,
        "instrument_ids": (
            [str(item) for item in request.instrument_ids]
            if request.instrument_ids is not None
            else None
        ),
        "exchange_codes": (
            list(request.exchange_codes) if request.exchange_codes is not None else None
        ),
        "asset_classes": (
            list(request.asset_classes) if request.asset_classes is not None else None
        ),
        "currency": request.currency,
        "calendar_code": request.calendar_code,
        "require_open_session": request.require_open_session,
        "allow_unfiltered": request.allow_unfiltered,
    }


def quality_request_mapping(request: DatasetSnapshotRequest) -> dict[str, object]:
    payload = dataset_request_mapping(request.dataset)
    payload["strict_calendar"] = request.strict_calendar
    payload["long_gap_open_sessions"] = request.long_gap_open_sessions
    return payload


def hash_daily_bars_dataset(
    dataset: DailyBarsDataset | Sequence[DailyBarDatasetRow],
) -> str:
    """SHA-256 of PIT-visible daily bars. Corporate actions are not included."""
    rows = dataset.rows if isinstance(dataset, DailyBarsDataset) else dataset
    ordered = sorted(rows, key=_bar_sort_key)
    payload = {
        "kind": DATASET_HASH_KIND,
        "version": HASH_FORMAT_VERSION,
        "columns": list(DAILY_BAR_DATASET_COLUMNS),
        "rows": [_canonical_bar_row(row) for row in ordered],
    }
    return sha256_canonical(payload)


def hash_quality_mapping(
    mapping: Mapping[str, object],
    *,
    include_generated_at: bool = False,
) -> str:
    """SHA-256 of a quality-report JSON object (from memory or quality.json)."""
    report = dict(mapping)
    if not include_generated_at:
        report.pop("generated_at", None)
    payload = {
        "kind": QUALITY_HASH_KIND,
        "version": HASH_FORMAT_VERSION,
        "report": report,
    }
    return sha256_canonical(payload)


def hash_quality_report(
    report: DatasetQualityReport,
    *,
    include_generated_at: bool = False,
) -> str:
    """SHA-256 of the quality report.

    ``generated_at`` is omitted unless ``include_generated_at=True``. Snapshots
    write ``generated_at`` into quality JSON for audit, but the stored
    ``quality_hash`` uses the default (exclude) so it tracks diagnostics, not
    wall-clock time.
    """
    return hash_quality_mapping(
        report.as_mapping(), include_generated_at=include_generated_at
    )


def hash_manifest_mapping(mapping: Mapping[str, object]) -> str:
    """SHA-256 of a manifest JSON object excluding ``manifest_hash``."""
    payload = dict(mapping)
    payload.pop("manifest_hash", None)
    return sha256_canonical(payload)


def get_git_commit(*, cwd: Path | None = None) -> str | None:
    """Return HEAD SHA1 for the local repo, or None if git is unavailable.

    Does not modify the repository or contact a remote. Ignores the accidental
    git directory at ``/home/isma``.
    """
    root = (cwd or _package_root()).resolve()
    git_bin = shutil.which("git")
    if git_bin is None:
        return None
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    try:
        toplevel = subprocess.run(  # noqa: S603
            [git_bin, "rev-parse", "--show-toplevel"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if toplevel.returncode != 0:
        return None
    git_root = Path(toplevel.stdout.strip()).resolve()
    if git_root == _ACCIDENTAL_GIT_ROOT.resolve():
        return None
    try:
        head = subprocess.run(  # noqa: S603
            [git_bin, "rev-parse", "HEAD"],
            cwd=git_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if head.returncode != 0:
        return None
    commit = head.stdout.strip()
    return commit or None


def create_daily_bars_snapshot(
    session: Session,
    request: DatasetSnapshotRequest,
    output_dir: Path | str,
    notes: str | None = None,
    *,
    created_at: datetime | None = None,
    snapshot_id: UUID | None = None,
    git_commit: str | None = None,
    resolve_git: bool = True,
) -> DatasetSnapshotResult:
    """Write dataset CSV, quality JSON, and manifest under ``output_dir``."""
    rebuilt = build_dataset_snapshot_request(
        as_of=request.dataset.as_of,
        start_time=request.dataset.start_time,
        end_time=request.dataset.end_time,
        symbols=request.dataset.symbols,
        instrument_ids=request.dataset.instrument_ids,
        exchange_codes=request.dataset.exchange_codes,
        asset_classes=request.dataset.asset_classes,
        currency=request.dataset.currency,
        calendar_code=request.dataset.calendar_code,
        require_open_session=request.dataset.require_open_session,
        allow_unfiltered=request.dataset.allow_unfiltered,
        strict_calendar=request.strict_calendar,
        long_gap_open_sessions=request.long_gap_open_sessions,
        notes=request.notes,
    )
    if rebuilt != request:
        raise DatasetValidationError(
            "DatasetSnapshotRequest must be built via build_dataset_snapshot_request",
            code=DatasetErrorCode.INVALID_RANGE,
        )
    stamp = created_at if created_at is not None else utc_now()
    if stamp.tzinfo is None:
        raise DatasetValidationError(
            "created_at must be timezone-aware UTC",
            code=DatasetErrorCode.NAIVE_TIMESTAMP,
        )
    stamp = stamp.astimezone(UTC)
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)

    dataset = get_daily_bars_dataset(session, request.dataset)
    quality_request = build_dataset_quality_request(
        as_of=request.dataset.as_of,
        start_time=request.dataset.start_time,
        end_time=request.dataset.end_time,
        symbols=request.dataset.symbols,
        instrument_ids=request.dataset.instrument_ids,
        exchange_codes=request.dataset.exchange_codes,
        asset_classes=request.dataset.asset_classes,
        currency=request.dataset.currency,
        calendar_code=request.dataset.calendar_code,
        require_open_session=request.dataset.require_open_session,
        allow_unfiltered=request.dataset.allow_unfiltered,
        strict_calendar=request.strict_calendar,
        long_gap_open_sessions=request.long_gap_open_sessions,
    )
    quality = get_dataset_quality_report(session, quality_request, generated_at=stamp)
    content_hash = hash_daily_bars_dataset(dataset)
    quality_hash = hash_quality_report(quality)
    daily_bars_path = target / DAILY_BARS_ARTIFACT_NAME
    quality_path = target / QUALITY_ARTIFACT_NAME
    manifest_path = target / MANIFEST_ARTIFACT_NAME
    write_daily_bars_csv(dataset, daily_bars_path)
    write_dataset_quality_json(quality, quality_path)

    resolved_commit = git_commit
    if resolve_git and resolved_commit is None:
        resolved_commit = get_git_commit()

    artifacts = (
        SnapshotArtifact(name="daily_bars", path=DAILY_BARS_ARTIFACT_NAME, kind="csv"),
        SnapshotArtifact(
            name="quality_report", path=QUALITY_ARTIFACT_NAME, kind="json"
        ),
        SnapshotArtifact(name="manifest", path=MANIFEST_ARTIFACT_NAME, kind="json"),
    )
    instrument_ids = {row.instrument_id for row in dataset.rows}
    draft = DatasetSnapshotManifest(
        snapshot_id=snapshot_id or uuid4(),
        created_at=stamp,
        package_version=__version__,
        git_commit=resolved_commit,
        dataset_request=dataset_request_mapping(request.dataset),
        quality_request=quality_request_mapping(request),
        row_count=len(dataset.rows),
        instrument_count=len(instrument_ids),
        error_count=quality.error_count,
        warning_count=quality.warning_count,
        info_count=quality.info_count,
        content_hash=content_hash,
        quality_hash=quality_hash,
        manifest_hash="",
        artifacts=artifacts,
        notes=_coalesce_notes(notes, request.notes),
    )
    manifest_hash = hash_manifest_mapping(draft.as_mapping(include_manifest_hash=False))
    manifest = replace(draft, manifest_hash=manifest_hash)
    write_snapshot_manifest(manifest, manifest_path)
    return DatasetSnapshotResult(
        manifest=manifest,
        output_dir=target,
        daily_bars_path=daily_bars_path,
        quality_path=quality_path,
        manifest_path=manifest_path,
    )


def write_snapshot_manifest(manifest: DatasetSnapshotManifest, path: Path) -> None:
    text = (
        json.dumps(manifest.as_mapping(), indent=2, sort_keys=True, ensure_ascii=True)
        + "\n"
    )
    _reject_secrets(text)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _package_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _coalesce_notes(override: str | None, request_notes: str | None) -> str | None:
    if override is not None:
        stripped = override.strip()
        return stripped or None
    return request_notes


def _bar_sort_key(row: DailyBarDatasetRow) -> tuple[Any, ...]:
    return (
        row.symbol,
        row.exchange_code or "",
        str(row.instrument_id),
        canonical_datetime(row.observation_time),
        row.source_name,
    )


def _canonical_bar_row(row: DailyBarDatasetRow) -> list[object]:
    values: dict[str, object] = {
        "instrument_id": str(row.instrument_id),
        "symbol": row.symbol,
        "exchange_code": row.exchange_code or "",
        "asset_class": row.asset_class,
        "currency": row.currency or "",
        "observation_time": canonical_datetime(row.observation_time),
        "available_time": canonical_datetime(row.available_time),
        "open": canonical_decimal(row.open),
        "high": canonical_decimal(row.high),
        "low": canonical_decimal(row.low),
        "close": canonical_decimal(row.close),
        "volume": canonical_decimal(row.volume),
        "source_name": row.source_name,
        "ingestion_run_id": str(row.ingestion_run_id),
        "is_correction": row.is_correction,
        "correction_reason": row.correction_reason or "",
    }
    return [values[column] for column in DAILY_BAR_DATASET_COLUMNS]


def _reject_secrets(text: str) -> None:
    lowered = text.lower()
    for marker in _SECRET_MARKERS:
        if marker.lower() in lowered:
            raise DatasetValidationError(
                "snapshot output must not contain secrets",
                code=DatasetErrorCode.INVALID_RANGE,
            )


def manifest_contains_secrets(payload: Mapping[str, object] | str) -> bool:
    text = payload if isinstance(payload, str) else canonical_json(dict(payload))
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in _SECRET_MARKERS)
