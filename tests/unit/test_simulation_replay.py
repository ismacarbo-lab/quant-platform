"""Dataset replay without Docker. No strategies or trading."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from quant_platform.research.export import write_daily_bars_csv
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
from quant_platform.research.types import (
    DailyBarDatasetRow,
    DailyBarsDataset,
    build_daily_bars_dataset_request,
)
from quant_platform.simulation.clock import SimulationClock
from quant_platform.simulation.errors import SimulationError, SimulationErrorCode
from quant_platform.simulation.events import (
    MARKET_BAR_KIND,
    REPLAY_FINISHED_KIND,
    REPLAY_STARTED_KIND,
    ReplayFinishedEvent,
    ReplayStartedEvent,
    market_bar_event_from_row,
)
from quant_platform.simulation.replay import (
    replay_daily_bars_dataset,
    replay_daily_bars_snapshot,
)
from quant_platform.simulation.summary import SOURCE_SNAPSHOT


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


def _request(**overrides: object):
    values: dict[str, object] = {
        "as_of": datetime(2024, 1, 10, tzinfo=UTC),
        "start_time": datetime(2024, 1, 1, tzinfo=UTC),
        "end_time": datetime(2024, 1, 5, tzinfo=UTC),
        "symbols": ["FICT"],
    }
    values.update(overrides)
    return build_daily_bars_dataset_request(**values)  # type: ignore[arg-type]


def _dataset(
    rows: tuple[DailyBarDatasetRow, ...], **request_overrides: object
) -> DailyBarsDataset:
    return DailyBarsDataset(request=_request(**request_overrides), rows=rows)


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
) -> DatasetSnapshotManifest:
    bars = rows or (_bar(),)
    write_daily_bars_csv(bars, directory / "daily_bars.csv")
    quality_payload: dict[str, object] = {
        "generated_at": "2024-01-10T00:00:00+00:00",
        "error_count": 0,
        "warning_count": 0,
        "info_count": 0,
        "total_rows": len(bars),
        "instrument_count": len({row.instrument_id for row in bars}),
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
        error_count=0,
        warning_count=0,
        info_count=0,
        content_hash=hash_daily_bars_dataset(bars),
        quality_hash=hash_quality_mapping(quality_payload),
        manifest_hash="",
        artifacts=_artifacts(),
        notes="replay fixture",
    )
    hashed = replace(
        draft,
        manifest_hash=hash_manifest_mapping(
            draft.as_mapping(include_manifest_hash=False)
        ),
    )
    write_snapshot_manifest(hashed, directory / "manifest.json")
    return hashed


def test_clock_rejects_naive_timestamps() -> None:
    clock = SimulationClock()
    with pytest.raises(SimulationError) as exc:
        clock.advance_to(datetime(2024, 1, 2))
    assert exc.value.code == SimulationErrorCode.NAIVE_TIMESTAMP
    with pytest.raises(SimulationError):
        SimulationClock(current_time=datetime(2024, 1, 2))


def test_clock_does_not_allow_rewind() -> None:
    clock = SimulationClock()
    later = datetime(2024, 1, 5, tzinfo=UTC)
    earlier = datetime(2024, 1, 2, tzinfo=UTC)
    clock.advance_to(later)
    with pytest.raises(SimulationError) as exc:
        clock.advance_to(earlier)
    assert exc.value.code == SimulationErrorCode.CLOCK_REGRESSION
    assert clock.current_time == later
    clock.advance_to(later)


def test_events_are_ordered_by_available_time() -> None:
    early_avail = _bar(
        symbol="ZZZ",
        observation_time=datetime(2024, 1, 4, tzinfo=UTC),
        available_time=datetime(2024, 1, 5, tzinfo=UTC),
    )
    late_avail = _bar(
        symbol="AAA",
        observation_time=datetime(2024, 1, 2, tzinfo=UTC),
        available_time=datetime(2024, 1, 8, tzinfo=UTC),
    )
    replay = replay_daily_bars_dataset(
        _dataset((late_avail, early_avail), symbols=["AAA", "ZZZ"])
    )
    bars = replay.bars
    assert [event.symbol for event in bars] == ["ZZZ", "AAA"]
    assert [event.event_time for event in bars] == [
        early_avail.available_time,
        late_avail.available_time,
    ]
    assert isinstance(replay.events[0], ReplayStartedEvent)
    assert isinstance(replay.events[-1], ReplayFinishedEvent)


def test_event_time_equals_available_time() -> None:
    row = _bar(
        observation_time=datetime(2024, 1, 2, tzinfo=UTC),
        available_time=datetime(2024, 1, 4, tzinfo=UTC),
    )
    event = market_bar_event_from_row(row)
    assert event.event_time == event.available_time
    assert event.event_time != event.observation_time
    replay = replay_daily_bars_dataset(_dataset((row,)))
    assert replay.bars[0].event_time == row.available_time


def test_no_trading_event_types_exist() -> None:
    import quant_platform.simulation.events as events_mod

    names = {name for name in dir(events_mod) if name.endswith("Event")}
    assert names == {
        "MarketBarEvent",
        "ReplayEvent",
        "ReplayFinishedEvent",
        "ReplayStartedEvent",
    }
    row = _bar()
    replay = replay_daily_bars_dataset(_dataset((row,)))
    kinds = {event.kind for event in replay}
    assert kinds == {REPLAY_STARTED_KIND, MARKET_BAR_KIND, REPLAY_FINISHED_KIND}
    mapping_keys = set(replay.bars[0].as_mapping())
    for forbidden in ("order", "trade", "fill", "signal", "position", "portfolio"):
        assert all(forbidden not in key for key in mapping_keys)


def test_summary_is_stable_for_same_request() -> None:
    row = _bar()
    dataset = _dataset((row,))
    replay_id = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    first = replay_daily_bars_dataset(dataset, replay_id=replay_id)
    second = replay_daily_bars_dataset(dataset, replay_id=replay_id)
    assert first.summary.as_mapping() == second.summary.as_mapping()
    assert [event.as_mapping() for event in first] == [
        event.as_mapping() for event in second
    ]
    assert first.summary.source_type == "database"
    assert first.summary.started_at == dataset.request.start_time
    assert first.summary.bar_count == 1
    assert first.summary.event_count == 3
    assert first.summary.content_hash == hash_daily_bars_dataset(dataset)


def test_replay_detects_lookahead() -> None:
    row = _bar(available_time=datetime(2024, 1, 20, tzinfo=UTC))
    with pytest.raises(SimulationError) as exc:
        replay_daily_bars_dataset(
            _dataset(
                (row,),
                as_of=datetime(2024, 1, 10, tzinfo=UTC),
                end_time=datetime(2024, 1, 25, tzinfo=UTC),
            )
        )
    assert exc.value.code == SimulationErrorCode.LOOKAHEAD


def test_snapshot_replay_from_local_fixture(tmp_path: Path) -> None:
    first = _bar(
        symbol="FICT",
        observation_time=datetime(2024, 1, 2, tzinfo=UTC),
        available_time=datetime(2024, 1, 8, tzinfo=UTC),
    )
    second = _bar(
        symbol="FICT",
        instrument_id=first.instrument_id,
        observation_time=datetime(2024, 1, 4, tzinfo=UTC),
        available_time=datetime(2024, 1, 5, tzinfo=UTC),
    )
    root = tmp_path / "snap"
    root.mkdir()
    manifest = _write_snapshot(root, rows=(first, second))
    replay = replay_daily_bars_snapshot(root)
    assert replay.summary.source_type == SOURCE_SNAPSHOT
    assert replay.summary.content_hash == manifest.content_hash
    assert [event.event_time for event in replay.bars] == [
        second.available_time,
        first.available_time,
    ]
    assert all(event.event_time == event.available_time for event in replay.bars)


def test_broken_snapshot_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "snap"
    root.mkdir()
    _write_snapshot(root)
    (root / "daily_bars.csv").unlink()
    with pytest.raises(SimulationError) as exc:
        replay_daily_bars_snapshot(root)
    assert exc.value.code == SimulationErrorCode.BROKEN_SNAPSHOT
