"""Read-only snapshot artifact integrity checks without a database."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from quant_platform.research.catalog import compare_dataset_snapshots
from quant_platform.research.catalog_integrity import (
    integrity_report_json,
    load_snapshot_daily_bar_rows,
    verify_snapshot_artifacts,
)
from quant_platform.research.export import write_daily_bars_csv
from quant_platform.research.integrity_types import (
    ArtifactVerificationReport,
    IntegrityIssueCode,
)
from quant_platform.research.snapshot_types import (
    DatasetSnapshotManifest,
    SnapshotArtifact,
)
from quant_platform.research.snapshots import (
    hash_daily_bars_dataset,
    hash_manifest_mapping,
    hash_quality_mapping,
    write_snapshot_manifest,
)
from quant_platform.research.types import DailyBarDatasetRow


def _bar(**overrides: object) -> DailyBarDatasetRow:
    values: dict[str, object] = {
        "instrument_id": uuid4(),
        "symbol": "FICT",
        "exchange_code": "XNAS",
        "asset_class": "equity",
        "currency": "USD",
        "observation_time": datetime(2024, 1, 2, tzinfo=UTC),
        "available_time": datetime(2024, 1, 3, tzinfo=UTC),
        "open": Decimal("10"),
        "high": Decimal("11"),
        "low": Decimal("9"),
        "close": Decimal("10.5"),
        "volume": Decimal("100"),
        "source_name": "local_csv",
        "ingestion_run_id": uuid4(),
        "is_correction": False,
        "correction_reason": None,
    }
    values.update(overrides)
    return DailyBarDatasetRow(**values)  # type: ignore[arg-type]


def _artifacts() -> tuple[SnapshotArtifact, ...]:
    return (
        SnapshotArtifact(name="daily_bars", path="daily_bars.csv", kind="csv"),
        SnapshotArtifact(name="quality_report", path="quality.json", kind="json"),
        SnapshotArtifact(name="manifest", path="manifest.json", kind="json"),
    )


def _write_snapshot(
    directory: Path,
    *,
    rows: tuple[DailyBarDatasetRow, ...] | None = None,
    quality: dict[str, object] | None = None,
    notes: str | None = "fixture",
    artifacts: tuple[SnapshotArtifact, ...] | None = None,
) -> DatasetSnapshotManifest:
    bars = rows or (_bar(),)
    write_daily_bars_csv(bars, directory / "daily_bars.csv")
    quality_payload = quality or {
        "generated_at": "2024-01-10T00:00:00+00:00",
        "error_count": 0,
        "warning_count": 0,
        "info_count": 0,
        "total_rows": len(bars),
        "instrument_count": 1,
    }
    (directory / "quality.json").write_text(
        json.dumps(quality_payload, indent=2) + "\n", encoding="utf-8"
    )
    draft = DatasetSnapshotManifest(
        snapshot_id=uuid4(),
        created_at=datetime(2024, 1, 10, tzinfo=UTC),
        package_version="0.1.0",
        git_commit="deadbeef",
        dataset_request={
            "as_of": "2024-01-10T00:00:00.000000Z",
            "start_time": "2024-01-01T00:00:00.000000Z",
            "end_time": "2024-01-05T00:00:00.000000Z",
            "symbols": ["FICT"],
        },
        quality_request={"as_of": "2024-01-10T00:00:00.000000Z"},
        row_count=len(bars),
        instrument_count=len({row.instrument_id for row in bars}),
        error_count=int(quality_payload.get("error_count") or 0),
        warning_count=int(quality_payload.get("warning_count") or 0),
        info_count=int(quality_payload.get("info_count") or 0),
        content_hash=hash_daily_bars_dataset(bars),
        quality_hash=hash_quality_mapping(quality_payload),
        manifest_hash="",
        artifacts=artifacts or _artifacts(),
        notes=notes,
    )
    hashed = replace(
        draft,
        manifest_hash=hash_manifest_mapping(
            draft.as_mapping(include_manifest_hash=False)
        ),
    )
    write_snapshot_manifest(hashed, directory / "manifest.json")
    return hashed


def _codes(report: ArtifactVerificationReport) -> set[str]:
    return {item.code for item in report.issues}


def test_csv_roundtrip_matches_content_hash(tmp_path: Path) -> None:
    row = _bar()
    write_daily_bars_csv((row,), tmp_path / "daily_bars.csv")
    loaded = load_snapshot_daily_bar_rows(tmp_path / "daily_bars.csv")
    assert hash_daily_bars_dataset(loaded) == hash_daily_bars_dataset((row,))


def test_valid_snapshot_verifies_clean(tmp_path: Path) -> None:
    root = tmp_path / "snap"
    root.mkdir()
    manifest = _write_snapshot(root)
    report = verify_snapshot_artifacts(root)
    assert report.ok is True
    assert report.error_count == 0
    assert report.snapshot_id == str(manifest.snapshot_id)
    assert report.recomputed_content_hash == manifest.content_hash
    assert report.recomputed_quality_hash == manifest.quality_hash
    assert report.recomputed_manifest_hash == manifest.manifest_hash


def test_relative_paths_are_accepted(tmp_path: Path) -> None:
    root = tmp_path / "snap"
    root.mkdir()
    _write_snapshot(root)
    report = verify_snapshot_artifacts(root)
    assert all(item.relative and not item.escaped for item in report.artifacts)


def test_absolute_artifact_path_rejected(tmp_path: Path) -> None:
    root = tmp_path / "snap"
    root.mkdir()
    _write_snapshot(root)
    payload = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    payload["artifacts"] = [
        {"name": "daily_bars", "path": "/abs/outside.csv", "kind": "csv"}
    ]
    (root / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    report = verify_snapshot_artifacts(root)
    assert report.ok is False
    assert IntegrityIssueCode.ABSOLUTE_PATH.value in _codes(report)


def test_path_traversal_rejected(tmp_path: Path) -> None:
    root = tmp_path / "snap"
    root.mkdir()
    _write_snapshot(root)
    payload = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    payload["artifacts"] = [
        {"name": "daily_bars", "path": "../secret.csv", "kind": "csv"}
    ]
    (root / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    report = verify_snapshot_artifacts(root)
    assert report.ok is False
    assert IntegrityIssueCode.PATH_ESCAPE.value in _codes(report)


def test_missing_artifact_is_an_error(tmp_path: Path) -> None:
    root = tmp_path / "snap"
    root.mkdir()
    _write_snapshot(root)
    (root / "daily_bars.csv").unlink()
    report = verify_snapshot_artifacts(root)
    assert report.ok is False
    assert IntegrityIssueCode.MISSING_ARTIFACT.value in _codes(report)


def test_secret_like_manifest_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "snap"
    root.mkdir()
    (root / "daily_bars.csv").write_text("instrument_id\n", encoding="utf-8")
    (root / "quality.json").write_text("{}\n", encoding="utf-8")
    payload = {
        "snapshot_id": str(uuid4()),
        "content_hash": "sha256:" + "a" * 64,
        "quality_hash": "sha256:" + "b" * 64,
        "manifest_hash": "sha256:" + "c" * 64,
        "notes": "postgresql://quant:secret@127.0.0.1/db",
        "artifacts": [
            {"name": "daily_bars", "path": "daily_bars.csv", "kind": "csv"},
        ],
        "row_count": 0,
        "instrument_count": 0,
        "dataset_request": {
            "as_of": "2024-01-10T00:00:00Z",
            "start_time": "2024-01-01T00:00:00Z",
            "end_time": "2024-01-05T00:00:00Z",
        },
    }
    (root / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    report = verify_snapshot_artifacts(root)
    assert IntegrityIssueCode.SECRET_LIKE_VALUE.value in _codes(report)
    dumped = integrity_report_json(report)
    assert "postgresql://" not in dumped
    assert "quant:secret" not in dumped


def test_invalid_hash_format(tmp_path: Path) -> None:
    root = tmp_path / "snap"
    root.mkdir()
    _write_snapshot(root)
    payload = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    payload["content_hash"] = "sha256:abc"
    (root / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    report = verify_snapshot_artifacts(root)
    assert IntegrityIssueCode.INVALID_HASH.value in _codes(report)


def test_manifest_hash_is_stable(tmp_path: Path) -> None:
    root = tmp_path / "snap"
    root.mkdir()
    manifest = _write_snapshot(root)
    payload = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert hash_manifest_mapping(payload) == manifest.manifest_hash
    assert hash_manifest_mapping(payload) == hash_manifest_mapping(dict(payload))


def test_quality_hash_mismatch(tmp_path: Path) -> None:
    root = tmp_path / "snap"
    root.mkdir()
    _write_snapshot(root)
    (root / "quality.json").write_text(
        json.dumps({"generated_at": "x", "error_count": 9}) + "\n", encoding="utf-8"
    )
    report = verify_snapshot_artifacts(root)
    assert report.ok is False
    assert IntegrityIssueCode.QUALITY_HASH_MISMATCH.value in _codes(report)


def test_content_hash_mismatch_when_csv_changes(tmp_path: Path) -> None:
    root = tmp_path / "snap"
    root.mkdir()
    first = _bar()
    _write_snapshot(root, rows=(first,))
    extra = _bar(instrument_id=first.instrument_id)
    write_daily_bars_csv((first, extra), root / "daily_bars.csv")
    report = verify_snapshot_artifacts(root)
    assert IntegrityIssueCode.CONTENT_HASH_MISMATCH.value in _codes(report)
    assert IntegrityIssueCode.ROW_COUNT_MISMATCH.value in _codes(report)


def test_compare_includes_package_and_artifact_paths() -> None:
    left_id = uuid4()
    right_id = uuid4()
    left = DatasetSnapshotManifest(
        snapshot_id=left_id,
        created_at=datetime(2024, 1, 10, tzinfo=UTC),
        package_version="0.1.0",
        git_commit="aaa",
        dataset_request={
            "as_of": "2024-01-10T00:00:00.000000Z",
            "start_time": "2024-01-01T00:00:00.000000Z",
            "end_time": "2024-01-05T00:00:00.000000Z",
            "symbols": ["FICT"],
        },
        quality_request={},
        row_count=1,
        instrument_count=1,
        error_count=0,
        warning_count=0,
        info_count=0,
        content_hash="sha256:" + "a" * 64,
        quality_hash="sha256:" + "b" * 64,
        manifest_hash="sha256:" + "c" * 64,
        artifacts=_artifacts(),
        notes=None,
    )
    right = replace(
        left,
        snapshot_id=right_id,
        package_version="0.2.0",
        artifacts=(SnapshotArtifact(name="daily_bars", path="other.csv", kind="csv"),),
        dataset_request={
            "as_of": "2024-01-10T00:00:00.000000Z",
            "start_time": "2024-02-01T00:00:00.000000Z",
            "end_time": "2024-02-05T00:00:00.000000Z",
            "symbols": ["FICT"],
        },
    )
    comparison = compare_dataset_snapshots(left, right)
    assert comparison.same_package_version is False
    assert comparison.same_artifact_paths is False
    assert comparison.same_start_time is False
    assert "package_version" in comparison.differences
    assert "artifact_paths" in comparison.differences


def test_integrity_json_is_stable(tmp_path: Path) -> None:
    root = tmp_path / "snap"
    root.mkdir()
    _write_snapshot(root)
    report = verify_snapshot_artifacts(root)
    first = integrity_report_json(report)
    second = integrity_report_json(report)
    assert first == second
    parsed = json.loads(first)
    assert parsed["ok"] is True
    assert list(parsed.keys()) == sorted(parsed.keys())
