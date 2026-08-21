"""Catalog validation, usability flags, and comparison without a database."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from quant_platform.research.catalog import (
    compare_dataset_snapshots,
    snapshot_is_reproducible,
    snapshot_is_usable,
    validate_catalog_manifest,
)
from quant_platform.research.catalog_types import (
    artifacts_have_absolute_paths,
    build_dataset_snapshot_catalog_filters,
)
from quant_platform.research.errors import DatasetErrorCode, DatasetValidationError
from quant_platform.research.snapshot_types import (
    DatasetSnapshotManifest,
    SnapshotArtifact,
)


def _digest(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode("utf-8")).hexdigest()


def _artifacts() -> tuple[SnapshotArtifact, ...]:
    return (
        SnapshotArtifact(name="daily_bars", path="daily_bars.csv", kind="csv"),
        SnapshotArtifact(name="quality_report", path="quality.json", kind="json"),
        SnapshotArtifact(name="manifest", path="manifest.json", kind="json"),
    )


def _manifest(**overrides: object) -> DatasetSnapshotManifest:
    values: dict[str, object] = {
        "snapshot_id": uuid4(),
        "created_at": datetime(2024, 1, 10, tzinfo=UTC),
        "package_version": "0.1.0",
        "git_commit": "deadbeef",
        "dataset_request": {
            "as_of": "2024-01-10T00:00:00.000000Z",
            "start_time": "2024-01-01T00:00:00.000000Z",
            "end_time": "2024-01-05T00:00:00.000000Z",
            "symbols": ["FICT"],
        },
        "quality_request": {
            "as_of": "2024-01-10T00:00:00.000000Z",
            "strict_calendar": False,
        },
        "row_count": 1,
        "instrument_count": 1,
        "error_count": 0,
        "warning_count": 0,
        "info_count": 0,
        "content_hash": _digest("content"),
        "quality_hash": _digest("quality"),
        "manifest_hash": _digest("manifest"),
        "artifacts": _artifacts(),
        "notes": "fixture",
    }
    values.update(overrides)
    return DatasetSnapshotManifest(**values)  # type: ignore[arg-type]


def test_valid_manifest_is_reproducible_and_usable() -> None:
    manifest = _manifest()
    validate_catalog_manifest(manifest)
    assert snapshot_is_reproducible(manifest) is True
    assert snapshot_is_usable(manifest) is True


def test_quality_errors_keep_reproducible_but_not_usable() -> None:
    manifest = _manifest(error_count=2)
    assert snapshot_is_reproducible(manifest) is True
    assert snapshot_is_usable(manifest) is False


def test_reject_short_hashes() -> None:
    manifest = _manifest(content_hash="sha256:abc")
    with pytest.raises(DatasetValidationError) as exc:
        validate_catalog_manifest(manifest)
    assert exc.value.code == DatasetErrorCode.CATALOG_INVALID
    assert snapshot_is_reproducible(manifest) is False
    assert snapshot_is_usable(manifest) is False


def test_reject_absolute_artifact_paths(tmp_path: Path) -> None:
    mapping = [{"name": "daily_bars", "path": str(tmp_path / "x.csv"), "kind": "csv"}]
    assert artifacts_have_absolute_paths(mapping) is True
    with pytest.raises(DatasetValidationError, match="relative"):
        validate_catalog_manifest(
            _manifest(
                artifacts=(
                    SnapshotArtifact(
                        name="daily_bars",
                        path=str(tmp_path / "daily_bars.csv"),
                        kind="csv",
                    ),
                )
            )
        )


def test_reject_secret_markers_in_notes() -> None:
    with pytest.raises(DatasetValidationError) as exc:
        validate_catalog_manifest(
            _manifest(notes="postgresql://quant:secret@127.0.0.1/db")
        )
    assert exc.value.code == DatasetErrorCode.CATALOG_INVALID


def test_compare_snapshots_reports_hash_and_count_diffs() -> None:
    left = _manifest(
        content_hash=_digest("a"),
        quality_hash=_digest("q1"),
        manifest_hash=_digest("m1"),
        row_count=1,
        error_count=0,
        git_commit="aaa",
    )
    right = _manifest(
        content_hash=_digest("b"),
        quality_hash=_digest("q1"),
        manifest_hash=_digest("m2"),
        row_count=3,
        error_count=1,
        git_commit="bbb",
        dataset_request={
            "as_of": "2024-02-01T00:00:00.000000Z",
            "start_time": "2024-01-01T00:00:00.000000Z",
            "end_time": "2024-01-05T00:00:00.000000Z",
            "symbols": ["FICT"],
        },
    )
    comparison = compare_dataset_snapshots(left, right)
    assert comparison.same_content_hash is False
    assert comparison.same_quality_hash is True
    assert comparison.same_manifest_hash is False
    assert comparison.same_as_of is False
    assert comparison.same_git_commit is False
    assert comparison.row_count_delta == 2
    assert comparison.error_count_delta == 1
    assert "content_hash" in comparison.differences
    assert "as_of" in comparison.differences


def test_catalog_filters_reject_empty_symbol_and_naive_bounds() -> None:
    with pytest.raises(DatasetValidationError) as exc:
        build_dataset_snapshot_catalog_filters(symbol="  ")
    assert exc.value.code == DatasetErrorCode.EMPTY_FILTER
    with pytest.raises(DatasetValidationError) as exc_naive:
        build_dataset_snapshot_catalog_filters(as_of_from=datetime(2024, 1, 1))
    assert exc_naive.value.code == DatasetErrorCode.NAIVE_TIMESTAMP
    filters = build_dataset_snapshot_catalog_filters(
        content_hash=_digest("x"),
        usable_only=True,
        symbol="FICT",
        as_of_from=datetime(2024, 1, 1, tzinfo=UTC),
        as_of_to=datetime(2024, 1, 10, tzinfo=UTC),
    )
    assert filters.usable_only is True
    assert filters.symbol == "FICT"
    assert filters.content_hash is not None
