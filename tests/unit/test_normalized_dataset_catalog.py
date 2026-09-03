"""Normalized-dataset catalog mapping and comparison without Docker."""

from __future__ import annotations

import hashlib
import importlib.util
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from quant_platform.research.normalization import (
    AdjustmentMode,
    assemble_normalized_dataset,
    build_normalization_request,
    build_normalized_dataset_registration,
    compare_normalized_datasets,
    deterministic_normalized_dataset_id,
    write_normalized_dataset_artifacts,
)
from quant_platform.research.normalization.catalog import (
    evaluate_normalized_dataset_entry_usability,
    hash_normalized_dataset_catalog_manifest,
    validate_normalized_dataset_entry,
)
from quant_platform.research.normalization.catalog_types import (
    COMPARISON_DIFFERENT,
    COMPARISON_IDENTICAL,
    COMPARISON_SAME_DATASET,
    NormalizedDatasetCatalogEntry,
    NormalizedDatasetUsabilityCode,
)
from quant_platform.research.normalization.errors import NormalizationError
from quant_platform.research.types import (
    CorporateActionDatasetRow,
    DailyBarDatasetRow,
    DailyBarsDataset,
)
from quant_platform.simulation.constructs import detect_trading_constructs

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
_ROOT = Path(__file__).resolve().parents[2] / "src" / "quant_platform" / "research"
_FORBIDDEN_METRIC_TOKENS = (
    "sharpe",
    "drawdown",
    "hit_ratio",
    "pnl",
    "returns",
)
_FAKE_HASH = "sha256:" + ("a" * 64)
_OTHER_HASH = "sha256:" + ("b" * 64)


def _digest(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode("utf-8")).hexdigest()


def _stamp(day: int, hour: int = 0) -> datetime:
    return datetime(2024, 1, day, hour, tzinfo=UTC)


def _bar() -> DailyBarDatasetRow:
    return DailyBarDatasetRow(
        instrument_id=UUID("11111111-1111-1111-1111-111111111111"),
        symbol="FICT",
        exchange_code="XNYS",
        asset_class="equity",
        currency="USD",
        observation_time=_stamp(2),
        available_time=_stamp(3),
        open=Decimal("40"),
        high=Decimal("41"),
        low=Decimal("39"),
        close=Decimal("40"),
        volume=Decimal("100"),
        source_name="local_csv",
        ingestion_run_id=UUID("22222222-2222-2222-2222-222222222222"),
        is_correction=False,
        correction_reason=None,
    )


def _action() -> CorporateActionDatasetRow:
    return CorporateActionDatasetRow(
        id=UUID("33333333-3333-3333-3333-333333333333"),
        instrument_id=UUID("11111111-1111-1111-1111-111111111111"),
        symbol="FICT",
        exchange_code="XNYS",
        asset_class="equity",
        action_type="split",
        effective_time=_stamp(10),
        available_time=_stamp(1, 20),
        quantity_before=Decimal("1"),
        quantity_after=Decimal("4"),
        cash_amount=None,
        currency=None,
        old_value=None,
        new_value=None,
        note="fixture",
    )


def _dataset():
    request = build_normalization_request(
        as_of=_stamp(20),
        start_time=_stamp(1),
        end_time=_stamp(5),
        source_name="local_csv",
        adjustment_mode=AdjustmentMode.SPLIT_ONLY,
        symbols=["FICT"],
    )
    raw = DailyBarsDataset(request=request.dataset_request(), rows=(_bar(),))
    return assemble_normalized_dataset(
        request=request,
        raw_dataset=raw,
        visible_actions=(_action(),),
    )


def _artifacts() -> tuple[dict[str, object], ...]:
    return (
        {
            "name": "normalized_daily_bars",
            "path": "normalized_daily_bars.csv",
            "kind": "csv",
        },
        {
            "name": "normalization_report",
            "path": "normalization_report.json",
            "kind": "json",
        },
        {
            "name": "normalization_manifest",
            "path": "normalization_manifest.json",
            "kind": "json",
        },
    )


def _entry(**overrides: object) -> NormalizedDatasetCatalogEntry:
    values: dict[str, object] = {
        "normalized_dataset_id": "nd-fixture",
        "dataset_hash": _FAKE_HASH,
        "raw_dataset_hash": _OTHER_HASH,
        "source_type": "local_artifacts",
        "source_snapshot_id": None,
        "source_replay_id": None,
        "adjustment_mode": "split_only",
        "as_of": _stamp(20),
        "start_time": _stamp(1),
        "end_time": _stamp(5),
        "symbol_count": 1,
        "bar_count": 1,
        "adjusted_bar_count": 1,
        "applied_action_count": 1,
        "warning_count": 0,
        "error_count": 0,
        "is_reproducible": True,
        "is_usable": True,
        "artifacts": _artifacts(),
        "request": {
            "as_of": "2024-01-20T00:00:00.000000Z",
            "start_time": "2024-01-01T00:00:00.000000Z",
            "end_time": "2024-01-05T00:00:00.000000Z",
            "source_name": "local_csv",
            "adjustment_mode": "split_only",
            "symbols": ["FICT"],
        },
        "report_summary": {
            "ok": True,
            "dataset_hash": _FAKE_HASH,
            "raw_dataset_hash": _OTHER_HASH,
            "bar_count": 1,
            "applied_action_count": 1,
            "issue_count": 0,
            "warning_count": 0,
            "error_count": 0,
            "issue_codes": [],
            "adjustment_mode": "split_only",
        },
        "manifest_hash": _digest("manifest"),
        "package_version": "0.1.0",
        "git_commit": None,
        "created_at": _stamp(20),
        "registered_at": _stamp(20),
        "notes": "fixture",
    }
    values.update(overrides)
    return NormalizedDatasetCatalogEntry(**values)  # type: ignore[arg-type]


def _load_script(filename: str):
    path = _SCRIPTS / filename
    spec = importlib.util.spec_from_file_location(filename.replace("-", "_"), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_registration_mapping_has_no_secrets(tmp_path: Path) -> None:
    dataset = _dataset()
    manifest = write_normalized_dataset_artifacts(dataset, tmp_path)
    entry = build_normalized_dataset_registration(
        dataset,
        manifest,
        normalized_dataset_id="nd-map",
        notes="catalog-fixture",
    )
    validate_normalized_dataset_entry(entry)
    payload = entry.as_mapping()
    blob = str(payload)
    assert "DATABASE_URL" not in blob
    assert "postgresql+psycopg://" not in blob
    assert payload["normalized_dataset_id"] == "nd-map"
    assert payload["dataset_hash"] == dataset.dataset_hash
    assert payload["notes"] == "catalog-fixture"
    assert all(not Path(str(item["path"])).is_absolute() for item in entry.artifacts)


def test_compare_identical_same_dataset_and_different() -> None:
    left = _entry()
    identical = replace(left, normalized_dataset_id="nd-right-same")
    comparison = compare_normalized_datasets(left, identical)
    assert comparison.verdict == COMPARISON_IDENTICAL
    assert comparison.same_manifest_hash is True

    same_dataset = replace(
        left,
        normalized_dataset_id="nd-same-hash",
        warning_count=2,
        manifest_hash=_digest("other-manifest"),
    )
    same = compare_normalized_datasets(left, same_dataset)
    assert same.verdict == COMPARISON_SAME_DATASET
    assert same.same_dataset_hash is True
    assert same.same_manifest_hash is False

    different = replace(
        left,
        normalized_dataset_id="nd-other",
        dataset_hash=_digest("other-dataset"),
        manifest_hash=_digest("other-again"),
    )
    drifted = compare_normalized_datasets(left, different)
    assert drifted.verdict == COMPARISON_DIFFERENT
    assert drifted.same_dataset_hash is False
    assert "dataset_hash" in drifted.differences


def test_usability_fails_when_artifact_missing(tmp_path: Path) -> None:
    report = evaluate_normalized_dataset_entry_usability(_entry(), tmp_path)
    assert report.usable is False
    assert any(
        item.code == NormalizedDatasetUsabilityCode.MISSING_ARTIFACT.value
        for item in report.issues
    )


def test_usability_fails_when_hash_invalid(tmp_path: Path) -> None:
    entry = replace(_entry(), dataset_hash="not-a-hash")
    report = evaluate_normalized_dataset_entry_usability(entry, tmp_path)
    assert report.usable is False
    assert any(
        item.code == NormalizedDatasetUsabilityCode.INVALID_HASH.value
        for item in report.issues
    )


def test_deterministic_id_is_stable() -> None:
    first = deterministic_normalized_dataset_id(
        dataset_hash=_FAKE_HASH,
        adjustment_mode="split_only",
        as_of=_stamp(20),
    )
    second = deterministic_normalized_dataset_id(
        dataset_hash=_FAKE_HASH,
        adjustment_mode="split_only",
        as_of=_stamp(20),
    )
    assert first == second
    drifted = deterministic_normalized_dataset_id(
        dataset_hash=_OTHER_HASH,
        adjustment_mode="split_only",
        as_of=_stamp(20),
    )
    assert drifted != first
    dataset = _dataset()
    left = build_normalized_dataset_registration(
        dataset, _fake_manifest(dataset), deterministic_id=True
    )
    right = build_normalized_dataset_registration(
        dataset, _fake_manifest(dataset), deterministic_id=True
    )
    assert left.normalized_dataset_id == right.normalized_dataset_id


def _fake_manifest(dataset):
    from quant_platform.research.normalization.artifacts import (
        default_normalization_artifacts,
    )
    from quant_platform.research.normalization.types import NormalizationManifest

    return NormalizationManifest(
        kind="normalized_daily_bars_manifest",
        format_version=1,
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
        artifacts=default_normalization_artifacts(),
        applied_actions_summary=(),
        package_version="0.1.0",
        git_commit=None,
        created_at=_stamp(20),
    )


def test_catalog_manifest_hash_is_stable() -> None:
    first = hash_normalized_dataset_catalog_manifest(
        dataset_hash=_FAKE_HASH,
        raw_dataset_hash=_OTHER_HASH,
        adjustment_mode="split_only",
        as_of=_stamp(20),
        start_time=_stamp(1),
        end_time=_stamp(5),
        symbol_count=1,
        bar_count=1,
        adjusted_bar_count=1,
        applied_action_count=1,
        warning_count=0,
        error_count=0,
        artifacts=_artifacts(),
        request={"source_name": "local_csv"},
        report_summary={"ok": True},
        source_type="local_artifacts",
        source_snapshot_id=None,
        source_replay_id=None,
    )
    second = hash_normalized_dataset_catalog_manifest(
        dataset_hash=_FAKE_HASH,
        raw_dataset_hash=_OTHER_HASH,
        adjustment_mode="split_only",
        as_of=_stamp(20),
        start_time=_stamp(1),
        end_time=_stamp(5),
        symbol_count=1,
        bar_count=1,
        adjusted_bar_count=1,
        applied_action_count=1,
        warning_count=0,
        error_count=0,
        artifacts=_artifacts(),
        request={"source_name": "local_csv"},
        report_summary={"ok": True},
        source_type="local_artifacts",
        source_snapshot_id=None,
        source_replay_id=None,
    )
    assert first == second
    assert first.startswith("sha256:")


def test_validate_rejects_secrets() -> None:
    try:
        validate_normalized_dataset_entry(
            replace(_entry(), notes="postgresql://quant:secret@127.0.0.1/db")
        )
    except NormalizationError as exc:
        assert exc.code
        return
    raise AssertionError("secret-like notes must be rejected")


def test_script_args_parse_help() -> None:
    for filename in (
        "build-normalized-dataset.py",
        "verify-normalized-dataset.py",
        "list-normalized-datasets.py",
        "check-normalized-dataset-usability.py",
        "compare-normalized-datasets.py",
    ):
        module = _load_script(filename)
        try:
            module.main(["--help"])
        except SystemExit as exc:
            assert exc.code == 0
        else:
            raise AssertionError(f"{filename} --help must exit 0")


def test_no_forbidden_metric_terms() -> None:
    dataset = _dataset()
    entry = build_normalized_dataset_registration(dataset, _fake_manifest(dataset))
    blob = str(entry.as_mapping()).lower()
    for token in _FORBIDDEN_METRIC_TOKENS:
        assert token not in blob


def test_no_trading_constructs_in_catalog_modules() -> None:
    findings = detect_trading_constructs()
    assert findings == ()
    for filename in ("catalog.py", "catalog_types.py"):
        text = (_ROOT / "normalization" / filename).read_text(encoding="utf-8")
        assert "class Strategy" not in text
        assert "class Signal" not in text
        assert "class Order" not in text
        assert "class Portfolio" not in text
        assert "class Broker" not in text
