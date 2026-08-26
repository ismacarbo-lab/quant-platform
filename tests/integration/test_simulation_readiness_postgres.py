"""PostgreSQL replay-run comparison and backtest readiness."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from quant_platform.data.models import Instrument, SimulationReplayRunRecord
from quant_platform.data.repository import (
    create_ingestion_run,
    insert_daily_bars,
    upsert_data_source,
    upsert_instrument,
)
from quant_platform.data.validation import DailyBarDraft
from quant_platform.research.types import build_daily_bars_dataset_request
from quant_platform.simulation.artifacts import write_replay_run_artifacts
from quant_platform.simulation.audit import audit_replay
from quant_platform.simulation.readiness import evaluate_replay_run_readiness
from quant_platform.simulation.readiness_types import ReplayRunReadinessCode
from quant_platform.simulation.replay import create_daily_bar_replay
from quant_platform.simulation.run_catalog import list_replay_runs, register_replay_run
from quant_platform.simulation.run_compare import diff_catalog_replay_runs
from quant_platform.simulation.run_types import build_replay_run_catalog_filters
from quant_platform.storage.database import list_public_tables

pytestmark = pytest.mark.postgres

_TRADING_TABLES = frozenset(
    {"trades", "orders", "fills", "signals", "strategies", "positions"}
)


def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:8]}"


def _insert_bar(
    session: Session, *, instrument: Instrument, source_id: UUID, run_id: UUID
) -> None:
    price = Decimal("10")
    insert_daily_bars(
        session,
        drafts=[
            DailyBarDraft(
                symbol=instrument.symbol,
                observation_time=datetime(2024, 1, 2, tzinfo=UTC),
                available_time=datetime(2024, 1, 3, tzinfo=UTC),
                open=price,
                high=price + Decimal("1"),
                low=price - Decimal("1"),
                close=price,
                volume=Decimal("100"),
            )
        ],
        instruments_by_symbol={instrument.symbol: instrument},
        source_id=source_id,
        ingestion_run_id=run_id,
    )


def _seed_replay(db_session: Session, *, prefix: str = "RDY"):
    source = upsert_data_source(db_session, name=_unique("src"), vendor="local_csv")
    instrument = upsert_instrument(
        db_session, symbol=_unique(prefix), asset_class="equity"
    )
    run = create_ingestion_run(db_session, source_id=source.id)
    _insert_bar(db_session, instrument=instrument, source_id=source.id, run_id=run.id)
    request = build_daily_bars_dataset_request(
        as_of=datetime(2024, 1, 10, tzinfo=UTC),
        start_time=datetime(2024, 1, 1, tzinfo=UTC),
        end_time=datetime(2024, 1, 5, tzinfo=UTC),
        symbols=[instrument.symbol],
    )
    replay = create_daily_bar_replay(db_session, request, deterministic_id=True)
    report = audit_replay(replay.events, as_of=replay.summary.as_of)
    return replay, report, request


def test_compare_equal_and_different_replay_runs(
    db_session: Session, tmp_path: Path, postgres_engine: Engine
) -> None:
    replay, report, request = _seed_replay(db_session, prefix="EQ")
    first = write_replay_run_artifacts(
        replay,
        report,
        tmp_path / "left",
        request=request,
        created_at=datetime(2024, 1, 10, tzinfo=UTC),
        resolve_git=False,
    )
    register_replay_run(db_session, first.manifest)
    second_replay = create_daily_bar_replay(db_session, request, deterministic_id=False)
    second_report = audit_replay(
        second_replay.events, as_of=second_replay.summary.as_of
    )
    second = write_replay_run_artifacts(
        second_replay,
        second_report,
        tmp_path / "right",
        request=request,
        created_at=datetime(2024, 1, 11, tzinfo=UTC),
        resolve_git=False,
    )
    register_replay_run(db_session, second.manifest)
    same = diff_catalog_replay_runs(
        db_session, str(first.manifest.replay_id), str(first.manifest.replay_id)
    )
    assert same.identical is True
    assert same.verdict == "identical"
    equal_stream = diff_catalog_replay_runs(
        db_session, str(first.manifest.replay_id), str(second.manifest.replay_id)
    )
    assert equal_stream.same_stream_hash is True
    assert equal_stream.same_manifest_hash is False
    assert equal_stream.verdict == "same_stream"
    other, other_report, other_request = _seed_replay(db_session, prefix="DF")
    other_result = write_replay_run_artifacts(
        other,
        other_report,
        tmp_path / "other",
        request=other_request,
        created_at=datetime(2024, 1, 10, tzinfo=UTC),
        resolve_git=False,
    )
    register_replay_run(db_session, other_result.manifest)
    different = diff_catalog_replay_runs(
        db_session,
        str(first.manifest.replay_id),
        str(other_result.manifest.replay_id),
    )
    assert different.same_stream_hash is False
    assert different.verdict == "different"
    listed = list_replay_runs(
        db_session,
        build_replay_run_catalog_filters(stream_hash=first.manifest.stream_hash),
    )
    listed_ids = {item.replay_id for item in listed}
    assert str(first.manifest.replay_id) in listed_ids
    assert str(second.manifest.replay_id) in listed_ids
    tables = set(list_public_tables(postgres_engine))
    assert tables.isdisjoint(_TRADING_TABLES)


def test_readiness_ok_with_artifacts(db_session: Session, tmp_path: Path) -> None:
    replay, report, request = _seed_replay(db_session, prefix="OK")
    output = tmp_path / "run"
    result = write_replay_run_artifacts(
        replay,
        report,
        output,
        request=request,
        created_at=datetime(2024, 1, 10, tzinfo=UTC),
        git_commit="deadbeef",
        resolve_git=False,
    )
    register_replay_run(db_session, result.manifest, base_path=output)
    report_ready = evaluate_replay_run_readiness(
        db_session, str(result.manifest.replay_id), output, research_mode=True
    )
    assert report_ready.ready_for_backtest is True
    assert report_ready.gate.artifacts_ok is True
    assert report_ready.boundary_ok is True


def test_readiness_fails_missing_events_jsonl(
    db_session: Session, tmp_path: Path
) -> None:
    replay, report, request = _seed_replay(db_session, prefix="MISS")
    output = tmp_path / "run"
    result = write_replay_run_artifacts(
        replay,
        report,
        output,
        request=request,
        created_at=datetime(2024, 1, 10, tzinfo=UTC),
        resolve_git=False,
    )
    register_replay_run(db_session, result.manifest)
    (output / "events.jsonl").unlink()
    report_ready = evaluate_replay_run_readiness(
        db_session, str(result.manifest.replay_id), output, research_mode=True
    )
    assert report_ready.ready_for_backtest is False
    codes = {item.code for item in report_ready.issues}
    assert ReplayRunReadinessCode.ARTIFACT_MISSING.value in codes


def test_readiness_fails_boundary_ok_false(db_session: Session, tmp_path: Path) -> None:
    replay, report, request = _seed_replay(db_session, prefix="BND")
    output = tmp_path / "run"
    result = write_replay_run_artifacts(
        replay,
        report,
        output,
        request=request,
        created_at=datetime(2024, 1, 10, tzinfo=UTC),
        resolve_git=False,
    )
    register_replay_run(db_session, result.manifest)
    row = db_session.scalars(
        select(SimulationReplayRunRecord).where(
            SimulationReplayRunRecord.replay_id == str(result.manifest.replay_id)
        )
    ).one()
    row.boundary_ok = False
    db_session.flush()
    report_ready = evaluate_replay_run_readiness(
        db_session, str(result.manifest.replay_id), output, research_mode=True
    )
    assert report_ready.ready_for_backtest is False
    codes = {item.code for item in report_ready.issues}
    assert ReplayRunReadinessCode.BOUNDARY_NOT_OK.value in codes


def test_readiness_fails_artifact_hash_mismatch(
    db_session: Session, tmp_path: Path
) -> None:
    replay, report, request = _seed_replay(db_session, prefix="HSH")
    output = tmp_path / "run"
    result = write_replay_run_artifacts(
        replay,
        report,
        output,
        request=request,
        created_at=datetime(2024, 1, 10, tzinfo=UTC),
        resolve_git=False,
    )
    register_replay_run(db_session, result.manifest)
    other, other_report, other_request = _seed_replay(db_session, prefix="ALT")
    other_dir = tmp_path / "other"
    write_replay_run_artifacts(
        other,
        other_report,
        other_dir,
        request=other_request,
        created_at=datetime(2024, 1, 10, tzinfo=UTC),
        resolve_git=False,
    )
    (output / "events.jsonl").write_text(
        (other_dir / "events.jsonl").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    report_ready = evaluate_replay_run_readiness(
        db_session, str(result.manifest.replay_id), output, research_mode=True
    )
    assert report_ready.ready_for_backtest is False
    codes = {item.code for item in report_ready.issues}
    assert ReplayRunReadinessCode.ARTIFACT_HASH_MISMATCH.value in codes
