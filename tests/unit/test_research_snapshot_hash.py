"""Stable hashing and manifest rules for research dataset snapshots."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from quant_platform.research.errors import DatasetErrorCode, DatasetValidationError
from quant_platform.research.quality_types import (
    DatasetCoverageSummary,
    DatasetQualityIssue,
    DatasetQualityReport,
    DatasetQualityRequest,
    InstrumentCoverageSummary,
    IssueSeverity,
    QualityIssueCode,
)
from quant_platform.research.snapshot_types import (
    DatasetSnapshotManifest,
    SnapshotArtifact,
    build_dataset_snapshot_request,
)
from quant_platform.research.snapshots import (
    canonical_datetime,
    canonical_decimal,
    get_git_commit,
    hash_daily_bars_dataset,
    hash_quality_report,
    manifest_contains_secrets,
    write_snapshot_manifest,
)
from quant_platform.research.types import (
    DailyBarDatasetRow,
    DailyBarsDataset,
    DailyBarsDatasetRequest,
    build_daily_bars_dataset_request,
)


def _request() -> DailyBarsDatasetRequest:
    return build_daily_bars_dataset_request(
        as_of=datetime(2024, 1, 10, tzinfo=UTC),
        start_time=datetime(2024, 1, 1, tzinfo=UTC),
        end_time=datetime(2024, 1, 5, tzinfo=UTC),
        symbols=["FICT"],
    )


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


def test_content_hash_is_stable_and_order_independent() -> None:
    first = _bar(instrument_id=uuid4(), close=Decimal("10.5"))
    second = _bar(
        instrument_id=first.instrument_id,
        observation_time=datetime(2024, 1, 3, tzinfo=UTC),
        available_time=datetime(2024, 1, 4, tzinfo=UTC),
        close=Decimal("11"),
    )
    forward = DailyBarsDataset(request=_request(), rows=(first, second))
    reverse = DailyBarsDataset(request=_request(), rows=(second, first))
    assert hash_daily_bars_dataset(forward) == hash_daily_bars_dataset(reverse)
    assert hash_daily_bars_dataset(forward).startswith("sha256:")


def test_content_hash_changes_when_price_changes() -> None:
    instrument_id = uuid4()
    run_id = uuid4()
    base = _bar(
        instrument_id=instrument_id, ingestion_run_id=run_id, close=Decimal("10")
    )
    changed = _bar(
        instrument_id=instrument_id,
        ingestion_run_id=run_id,
        observation_time=base.observation_time,
        available_time=base.available_time,
        close=Decimal("10.01"),
        open=base.open,
        high=base.high,
        low=base.low,
        volume=base.volume,
    )
    assert hash_daily_bars_dataset((base,)) != hash_daily_bars_dataset((changed,))


def test_decimal_and_utc_normalization() -> None:
    assert canonical_decimal(Decimal("10.5")) == canonical_decimal(
        Decimal("10.50000000")
    )
    offset_zero = timezone(timedelta(0))
    left = datetime(2024, 1, 2, tzinfo=UTC)
    right = datetime(2024, 1, 2, tzinfo=offset_zero)
    assert canonical_datetime(left) == canonical_datetime(right)
    assert canonical_datetime(left).endswith("Z")
    instrument_id = uuid4()
    run_id = uuid4()
    row_a = _bar(
        instrument_id=instrument_id,
        ingestion_run_id=run_id,
        close=Decimal("10.5"),
        observation_time=left,
        available_time=datetime(2024, 1, 3, tzinfo=UTC),
    )
    row_b = _bar(
        instrument_id=instrument_id,
        ingestion_run_id=run_id,
        close=Decimal("10.50000000"),
        open=row_a.open,
        high=row_a.high,
        low=row_a.low,
        volume=row_a.volume,
        observation_time=right,
        available_time=datetime(2024, 1, 3, tzinfo=offset_zero),
        is_correction=row_a.is_correction,
        correction_reason=row_a.correction_reason,
        symbol=row_a.symbol,
        exchange_code=row_a.exchange_code,
        asset_class=row_a.asset_class,
        currency=row_a.currency,
        source_name=row_a.source_name,
    )
    assert hash_daily_bars_dataset((row_a,)) == hash_daily_bars_dataset((row_b,))


def test_snapshot_request_requires_as_of() -> None:
    with pytest.raises(DatasetValidationError) as exc:
        build_dataset_snapshot_request(
            start_time=datetime(2024, 1, 1, tzinfo=UTC),
            end_time=datetime(2024, 1, 5, tzinfo=UTC),
            symbols=["FICT"],
        )
    assert exc.value.code == DatasetErrorCode.MISSING_AS_OF


def test_quality_hash_stable_when_generated_at_excluded() -> None:
    request = DatasetQualityRequest(dataset=_request())
    coverage = DatasetCoverageSummary(
        instrument_count=1,
        total_bars=1,
        source_names=("local_csv",),
        first_observation=datetime(2024, 1, 2, tzinfo=UTC),
        last_observation=datetime(2024, 1, 2, tzinfo=UTC),
        expected_open_sessions=None,
        missing_open_sessions=0,
        bars_outside_calendar=0,
        coverage_ratio=None,
        visible_corrections=0,
        pit_versions_as_of=1,
        correction_links_as_of=0,
    )
    instrument = InstrumentCoverageSummary(
        instrument_id=uuid4(),
        symbol="FICT",
        exchange_code="XNAS",
        asset_class="equity",
        currency="USD",
        calendar_code=None,
        first_observation=datetime(2024, 1, 2, tzinfo=UTC),
        last_observation=datetime(2024, 1, 2, tzinfo=UTC),
        bar_count=1,
        source_names=("local_csv",),
        expected_open_sessions=None,
        missing_open_sessions=0,
        bars_on_closed_sessions=0,
        bars_on_unknown_sessions=0,
        coverage_ratio=None,
        visible_corrections=0,
        has_calendar=False,
    )
    issue = DatasetQualityIssue(
        severity=IssueSeverity.WARNING,
        code=QualityIssueCode.MISSING_CALENDAR,
        message="no calendar",
        symbol="FICT",
        instrument_id=instrument.instrument_id,
    )

    def _report(generated: datetime) -> DatasetQualityReport:
        return DatasetQualityReport(
            request=request,
            generated_at=generated,
            as_of=request.dataset.as_of,
            start_time=request.dataset.start_time,
            end_time=request.dataset.end_time,
            total_rows=1,
            instrument_count=1,
            issue_count=1,
            error_count=0,
            warning_count=1,
            info_count=0,
            coverage=coverage,
            instruments=(instrument,),
            corporate_actions=(),
            ingestion_runs=(),
            issues=(issue,),
        )

    early = _report(datetime(2024, 1, 10, tzinfo=UTC))
    late = _report(datetime(2024, 1, 11, tzinfo=UTC))
    assert hash_quality_report(early) == hash_quality_report(late)
    assert hash_quality_report(early, include_generated_at=True) == hash_quality_report(
        early, include_generated_at=True
    )
    assert hash_quality_report(early, include_generated_at=True) != hash_quality_report(
        late, include_generated_at=True
    )


def test_manifest_uses_relative_paths_and_omits_secrets(tmp_path: Path) -> None:
    manifest = DatasetSnapshotManifest(
        snapshot_id=uuid4(),
        created_at=datetime(2024, 1, 10, tzinfo=UTC),
        package_version="0.1.0",
        git_commit="deadbeef",
        dataset_request={
            "as_of": "2024-01-10T00:00:00.000000Z",
            "start_time": "2024-01-01T00:00:00.000000Z",
            "end_time": "2024-01-05T00:00:00.000000Z",
        },
        quality_request={
            "as_of": "2024-01-10T00:00:00.000000Z",
            "start_time": "2024-01-01T00:00:00.000000Z",
            "end_time": "2024-01-05T00:00:00.000000Z",
        },
        row_count=1,
        instrument_count=1,
        error_count=0,
        warning_count=0,
        info_count=0,
        content_hash="sha256:abc",
        quality_hash="sha256:def",
        manifest_hash="sha256:ghi",
        artifacts=(
            SnapshotArtifact(name="daily_bars", path="daily_bars.csv", kind="csv"),
            SnapshotArtifact(name="quality_report", path="quality.json", kind="json"),
            SnapshotArtifact(name="manifest", path="manifest.json", kind="json"),
        ),
        notes="fixture",
    )
    mapping = manifest.as_mapping()
    assert mapping["artifacts"] == [
        {"name": "daily_bars", "path": "daily_bars.csv", "kind": "csv"},
        {"name": "quality_report", "path": "quality.json", "kind": "json"},
        {"name": "manifest", "path": "manifest.json", "kind": "json"},
    ]
    assert not manifest_contains_secrets(mapping)
    path = tmp_path / "manifest.json"
    write_snapshot_manifest(manifest, path)
    text = path.read_text(encoding="utf-8")
    assert "DATABASE_URL" not in text
    assert str(tmp_path) not in text
    for artifact in mapping["artifacts"]:
        assert isinstance(artifact, dict)
        assert not str(artifact["path"]).startswith("/")
    with pytest.raises(DatasetValidationError, match="relative"):
        SnapshotArtifact(
            name="bad", path=str(tmp_path / "x.csv"), kind="csv"
        ).as_mapping()


def test_git_helper_returns_none_outside_a_repo(tmp_path: Path) -> None:
    assert get_git_commit(cwd=tmp_path) is None
