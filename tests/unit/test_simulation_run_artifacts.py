"""Replay-run artifacts, hashes, and catalog helpers without Docker."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from quant_platform.research.types import (
    DailyBarDatasetRow,
    DailyBarsDataset,
    build_daily_bars_dataset_request,
)
from quant_platform.simulation.artifacts import (
    hash_replay_events_jsonl,
    load_replay_events_jsonl,
    write_replay_run_artifacts,
)
from quant_platform.simulation.audit import audit_replay
from quant_platform.simulation.errors import SimulationError, SimulationErrorCode
from quant_platform.simulation.hashing import hash_replay_events
from quant_platform.simulation.replay import replay_daily_bars_dataset
from quant_platform.simulation.run_catalog import (
    compare_replay_runs,
    raise_if_manifest_hash_conflict,
    replay_run_is_reproducible,
    replay_run_is_usable,
    validate_replay_run_manifest,
)
from quant_platform.simulation.run_integrity import (
    ReplayRunIntegrityCode,
    verify_replay_run_artifacts,
)
from quant_platform.simulation.run_types import (
    ReplayRunArtifact,
    ReplayRunCatalogEntry,
    ReplayRunManifest,
    artifacts_have_unsafe_paths,
    default_replay_run_artifacts,
)

_TRADING_FRAGMENTS = ("order", "trade", "fill", "signal", "position", "portfolio")
_DIGEST = "sha256:" + ("a" * 64)
_OTHER = "sha256:" + ("b" * 64)


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


def _dataset(rows: tuple[DailyBarDatasetRow, ...]) -> DailyBarsDataset:
    return DailyBarsDataset(
        request=build_daily_bars_dataset_request(
            as_of=datetime(2024, 1, 10, tzinfo=UTC),
            start_time=datetime(2024, 1, 1, tzinfo=UTC),
            end_time=datetime(2024, 1, 5, tzinfo=UTC),
            symbols=["FICT"],
        ),
        rows=rows,
    )


def _replay_and_audit():
    replay = replay_daily_bars_dataset(
        _dataset((_bar(),)),
        replay_id=UUID("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"),
    )
    report = audit_replay(replay.events, as_of=replay.summary.as_of)
    return replay, report


def _manifest(**overrides: object) -> ReplayRunManifest:
    values: dict[str, object] = {
        "replay_id": UUID("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"),
        "created_at": datetime(2024, 1, 10, tzinfo=UTC),
        "package_version": "0.1.0",
        "git_commit": "deadbeef",
        "source_type": "database",
        "dataset_snapshot_id": None,
        "dataset_content_hash": _DIGEST,
        "stream_hash": _DIGEST,
        "event_count": 3,
        "event_counts_by_type": {
            "market_bar": 1,
            "replay_finished": 1,
            "replay_started": 1,
        },
        "pre_known_event_count": 0,
        "boundary_ok": True,
        "warning_count": 0,
        "error_count": 0,
        "first_event_time": datetime(2024, 1, 3, tzinfo=UTC),
        "last_event_time": datetime(2024, 1, 3, tzinfo=UTC),
        "first_market_event_time": datetime(2024, 1, 3, tzinfo=UTC),
        "last_market_event_time": datetime(2024, 1, 3, tzinfo=UTC),
        "request": {
            "as_of": "2024-01-10T00:00:00.000000Z",
            "start_time": "2024-01-01T00:00:00.000000Z",
            "end_time": "2024-01-05T00:00:00.000000Z",
            "symbols": ["FICT"],
        },
        "audit_summary": {"ok": True, "boundary_ok": True, "error_count": 0},
        "artifacts": default_replay_run_artifacts(),
        "notes": "fixture",
        "manifest_hash": _OTHER,
    }
    values.update(overrides)
    return ReplayRunManifest(**values)  # type: ignore[arg-type]


def _entry(**overrides: object) -> ReplayRunCatalogEntry:
    values: dict[str, object] = {
        "replay_id": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
        "stream_hash": _DIGEST,
        "manifest_hash": _OTHER,
        "source_type": "database",
        "dataset_snapshot_id": None,
        "dataset_content_hash": _DIGEST,
        "package_version": "0.1.0",
        "git_commit": "deadbeef",
        "created_at": datetime(2024, 1, 10, tzinfo=UTC),
        "as_of": datetime(2024, 1, 10, tzinfo=UTC),
        "start_time": datetime(2024, 1, 1, tzinfo=UTC),
        "end_time": datetime(2024, 1, 5, tzinfo=UTC),
        "event_count": 3,
        "market_event_count": 1,
        "session_event_count": 0,
        "corporate_action_event_count": 0,
        "pre_known_event_count": 0,
        "warning_count": 0,
        "error_count": 0,
        "boundary_ok": True,
        "is_reproducible": True,
        "is_usable": True,
        "request": {"symbols": ["FICT"]},
        "audit_summary": {"ok": True},
        "artifacts": tuple(
            item.as_mapping() for item in default_replay_run_artifacts()
        ),
        "notes": None,
        "registered_at": datetime(2024, 1, 10, tzinfo=UTC),
    }
    values.update(overrides)
    return ReplayRunCatalogEntry(**values)  # type: ignore[arg-type]


def test_manifest_contains_no_secrets(tmp_path: Path) -> None:
    replay, report = _replay_and_audit()
    result = write_replay_run_artifacts(
        replay,
        report,
        tmp_path / "run",
        created_at=datetime(2024, 1, 10, tzinfo=UTC),
        resolve_git=False,
    )
    blob = str(result.manifest.as_mapping())
    assert "DATABASE_URL" not in blob
    assert "postgresql://" not in blob.lower()
    text = (tmp_path / "run" / "manifest.json").read_text(encoding="utf-8")
    assert "DATABASE_URL" not in text
    with pytest.raises(SimulationError) as exc:
        write_replay_run_artifacts(
            replay,
            report,
            tmp_path / "secret",
            created_at=datetime(2024, 1, 10, tzinfo=UTC),
            notes="DATABASE_URL=postgresql://example",
            resolve_git=False,
        )
    assert exc.value.code == SimulationErrorCode.CATALOG_INVALID


def test_artifact_paths_are_relative(tmp_path: Path) -> None:
    replay, report = _replay_and_audit()
    result = write_replay_run_artifacts(
        replay,
        report,
        tmp_path / "run",
        created_at=datetime(2024, 1, 10, tzinfo=UTC),
        resolve_git=False,
    )
    for item in result.manifest.artifacts:
        assert not Path(item.path).is_absolute()
        assert ".." not in Path(item.path).parts
    mapping = [item.as_mapping() for item in result.manifest.artifacts]
    assert artifacts_have_unsafe_paths(mapping) is False


def test_reject_absolute_artifact_path() -> None:
    with pytest.raises(SimulationError) as exc:
        ReplayRunArtifact(
            name="events", path="/absolute/events.jsonl", kind="jsonl"
        ).as_mapping()
    assert exc.value.code == SimulationErrorCode.CATALOG_INVALID
    assert artifacts_have_unsafe_paths(
        [{"name": "events", "path": "/absolute/events.jsonl", "kind": "jsonl"}]
    )
    assert artifacts_have_unsafe_paths(
        [{"name": "events", "path": "../events.jsonl", "kind": "jsonl"}]
    )


def test_events_jsonl_is_stable(tmp_path: Path) -> None:
    replay, report = _replay_and_audit()
    first = write_replay_run_artifacts(
        replay,
        report,
        tmp_path / "one",
        created_at=datetime(2024, 1, 10, tzinfo=UTC),
        resolve_git=False,
    )
    second = write_replay_run_artifacts(
        replay,
        report,
        tmp_path / "two",
        created_at=datetime(2024, 1, 10, tzinfo=UTC),
        resolve_git=False,
    )
    left = (tmp_path / "one" / "events.jsonl").read_text(encoding="utf-8")
    right = (tmp_path / "two" / "events.jsonl").read_text(encoding="utf-8")
    assert left == right
    assert first.manifest.stream_hash == second.manifest.stream_hash
    assert first.manifest.manifest_hash == second.manifest.manifest_hash
    assert "Z" in left


def test_stream_hash_recomputed_from_jsonl(tmp_path: Path) -> None:
    replay, report = _replay_and_audit()
    result = write_replay_run_artifacts(
        replay,
        report,
        tmp_path / "run",
        created_at=datetime(2024, 1, 10, tzinfo=UTC),
        resolve_git=False,
    )
    events = load_replay_events_jsonl(tmp_path / "run" / "events.jsonl")
    assert hash_replay_events(events) == result.manifest.stream_hash
    assert (
        hash_replay_events_jsonl(tmp_path / "run" / "events.jsonl")
        == result.manifest.stream_hash
    )
    integrity = verify_replay_run_artifacts(tmp_path / "run")
    assert integrity.ok is True
    assert integrity.recomputed_stream_hash == result.manifest.stream_hash


def test_compare_replay_runs_reports_stream_hash_diff() -> None:
    left = _manifest()
    right = _manifest(
        replay_id=uuid4(),
        stream_hash=_OTHER,
        event_count=4,
        error_count=1,
        boundary_ok=False,
    )
    comparison = compare_replay_runs(left, right)
    assert comparison.same_stream_hash is False
    assert comparison.same_manifest_hash is True
    assert "stream_hash" in comparison.differences
    assert comparison.event_count_delta == 1
    assert comparison.error_count_delta == 1


def test_usable_requires_zero_errors_and_boundary() -> None:
    ok = _manifest()
    validate_replay_run_manifest(ok)
    assert replay_run_is_reproducible(ok) is True
    assert replay_run_is_usable(ok) is True
    broken_audit = _manifest(error_count=2, boundary_ok=True)
    assert replay_run_is_reproducible(broken_audit) is True
    assert replay_run_is_usable(broken_audit) is False
    broken_boundary = _manifest(error_count=0, boundary_ok=False)
    assert replay_run_is_usable(broken_boundary) is False
    invalid = _manifest(stream_hash="sha256:abc")
    with pytest.raises(SimulationError) as exc:
        validate_replay_run_manifest(invalid)
    assert exc.value.code == SimulationErrorCode.CATALOG_INVALID
    assert replay_run_is_reproducible(invalid) is False


def test_duplicate_manifest_hash_detected_in_pure_logic() -> None:
    manifest = _manifest()
    owner = _entry(replay_id="bbbbbbbb-bbbb-4ccc-8ddd-eeeeeeeeeeee")
    with pytest.raises(SimulationError) as exc:
        raise_if_manifest_hash_conflict(owner, manifest)
    assert exc.value.code == SimulationErrorCode.CATALOG_CONFLICT
    raise_if_manifest_hash_conflict(_entry(replay_id=str(manifest.replay_id)), manifest)
    raise_if_manifest_hash_conflict(None, manifest)


def test_no_trading_events_in_run_artifacts(tmp_path: Path) -> None:
    replay, report = _replay_and_audit()
    write_replay_run_artifacts(
        replay,
        report,
        tmp_path / "run",
        created_at=datetime(2024, 1, 10, tzinfo=UTC),
        resolve_git=False,
    )
    text = (tmp_path / "run" / "events.jsonl").read_text(encoding="utf-8").lower()
    for fragment in _TRADING_FRAGMENTS:
        assert fragment not in text
    integrity = verify_replay_run_artifacts(tmp_path / "run")
    assert integrity.ok is True
    assert ReplayRunIntegrityCode.STREAM_HASH_MISMATCH.value not in {
        item.code for item in integrity.issues
    }


def test_metadata_has_replay_runs_table_not_trading() -> None:
    from quant_platform.data import models as _models  # noqa: F401
    from quant_platform.storage.database import Base

    names = set(Base.metadata.tables)
    assert "simulation_replay_runs" in names
    for fragment in _TRADING_FRAGMENTS:
        assert fragment not in names
    assert names.isdisjoint(
        {"orders", "trades", "fills", "signals", "strategies", "positions"}
    )
