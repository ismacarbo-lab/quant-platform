"""PostgreSQL replay-run catalog: artifacts, register, list, compare."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from quant_platform.core.config import clear_settings_cache
from quant_platform.data.models import Instrument
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
from quant_platform.simulation.errors import SimulationError, SimulationErrorCode
from quant_platform.simulation.replay import create_daily_bar_replay
from quant_platform.simulation.run_catalog import (
    compare_replay_runs,
    get_replay_run_by_id,
    get_replay_run_by_manifest_hash,
    list_replay_runs,
    register_replay_run,
)
from quant_platform.simulation.run_integrity import verify_registered_replay_run
from quant_platform.simulation.run_types import build_replay_run_catalog_filters
from quant_platform.storage.database import list_public_tables

pytestmark = pytest.mark.postgres

ROOT = Path(__file__).resolve().parents[2]
_REPLAY_RUN_TABLES = frozenset({"simulation_replay_runs"})
_BACKTEST_TABLES = frozenset({"backtest_runs", "backtest_experiments"})
_TRADING_TABLES = frozenset(
    {"trades", "orders", "fills", "signals", "strategies", "positions"}
)


def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:8]}"


def _digest(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode("utf-8")).hexdigest()


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


def _seed_replay(db_session: Session, *, prefix: str = "RUN"):
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


def test_replay_run_revision_downgrade_and_upgrade(postgres_engine: Engine) -> None:
    clear_settings_cache()
    cfg = Config(str(ROOT / "alembic.ini"))
    try:
        command.downgrade(cfg, "0005_catalog")
        inspect(postgres_engine).clear_cache()
        tables = set(list_public_tables(postgres_engine))
        assert tables.isdisjoint(_REPLAY_RUN_TABLES)
        assert tables.isdisjoint(_BACKTEST_TABLES)
    finally:
        command.upgrade(cfg, "head")
        inspect(postgres_engine).clear_cache()
    tables = set(list_public_tables(postgres_engine))
    assert _REPLAY_RUN_TABLES <= tables
    assert _BACKTEST_TABLES <= tables
    assert tables.isdisjoint(_TRADING_TABLES)


def test_write_and_register_replay_run(
    db_session: Session, tmp_path: Path, postgres_engine: Engine
) -> None:
    before = set(list_public_tables(postgres_engine))
    replay, report, request = _seed_replay(db_session)
    result = write_replay_run_artifacts(
        replay,
        report,
        tmp_path / "run",
        request=request,
        created_at=datetime(2024, 1, 10, tzinfo=UTC),
        resolve_git=False,
    )
    assert (tmp_path / "run" / "events.jsonl").is_file()
    assert (tmp_path / "run" / "audit.json").is_file()
    assert (tmp_path / "run" / "summary.json").is_file()
    assert (tmp_path / "run" / "manifest.json").is_file()
    inserted = register_replay_run(
        db_session, result.manifest, base_path=tmp_path / "run"
    )
    assert inserted.action == "insert"
    assert inserted.entry.is_usable is True
    assert inserted.entry.boundary_ok is True
    assert inserted.entry.stream_hash == result.manifest.stream_hash
    loaded = get_replay_run_by_id(db_session, str(result.manifest.replay_id))
    by_hash = get_replay_run_by_manifest_hash(db_session, result.manifest.manifest_hash)
    assert loaded is not None and by_hash is not None
    assert loaded.replay_id == by_hash.replay_id
    after = set(list_public_tables(postgres_engine))
    assert after == before
    assert after.isdisjoint(_TRADING_TABLES)


def test_register_upserts_by_replay_id(db_session: Session, tmp_path: Path) -> None:
    replay, report, request = _seed_replay(db_session, prefix="UPS")
    result = write_replay_run_artifacts(
        replay,
        report,
        tmp_path / "run",
        request=request,
        created_at=datetime(2024, 1, 10, tzinfo=UTC),
        notes="first",
        resolve_git=False,
    )
    first = register_replay_run(db_session, result.manifest)
    assert first.action == "insert"
    updated_manifest = replace(result.manifest, notes="second")
    second = register_replay_run(db_session, updated_manifest)
    assert second.action == "update"
    loaded = get_replay_run_by_id(db_session, str(result.manifest.replay_id))
    assert loaded is not None
    assert loaded.notes == "second"


def test_register_same_manifest_hash_different_id_conflicts(
    db_session: Session, tmp_path: Path
) -> None:
    replay, report, request = _seed_replay(db_session, prefix="CF")
    result = write_replay_run_artifacts(
        replay,
        report,
        tmp_path / "run",
        request=request,
        created_at=datetime(2024, 1, 10, tzinfo=UTC),
        resolve_git=False,
    )
    register_replay_run(db_session, result.manifest)
    other = replace(result.manifest, replay_id=uuid4())
    with pytest.raises(SimulationError) as exc:
        register_replay_run(db_session, other)
    assert exc.value.code == SimulationErrorCode.CATALOG_CONFLICT


def test_list_replay_runs_by_stream_hash_and_usable(
    db_session: Session, tmp_path: Path
) -> None:
    replay, report, request = _seed_replay(db_session, prefix="LST")
    result = write_replay_run_artifacts(
        replay,
        report,
        tmp_path / "ok",
        request=request,
        created_at=datetime(2024, 1, 10, tzinfo=UTC),
        resolve_git=False,
    )
    register_replay_run(db_session, result.manifest)
    broken = replace(
        result.manifest,
        replay_id=uuid4(),
        error_count=2,
        boundary_ok=True,
        manifest_hash=_digest("broken-run"),
    )
    register_replay_run(db_session, broken)
    by_hash = list_replay_runs(
        db_session,
        build_replay_run_catalog_filters(stream_hash=result.manifest.stream_hash),
    )
    assert {item.replay_id for item in by_hash} == {
        str(result.manifest.replay_id),
        str(broken.replay_id),
    }
    usable = list_replay_runs(
        db_session, build_replay_run_catalog_filters(usable_only=True)
    )
    usable_ids = {item.replay_id for item in usable}
    assert str(result.manifest.replay_id) in usable_ids
    assert str(broken.replay_id) not in usable_ids
    bounded = list_replay_runs(
        db_session, build_replay_run_catalog_filters(boundary_ok=True)
    )
    assert all(item.boundary_ok for item in bounded)
    comparison = compare_replay_runs(result.manifest, broken)
    assert comparison.same_stream_hash is True
    assert comparison.error_count_delta == 2
    catalog_ok = get_replay_run_by_id(db_session, str(result.manifest.replay_id))
    catalog_broken = get_replay_run_by_id(db_session, str(broken.replay_id))
    assert catalog_ok is not None and catalog_broken is not None
    listed_cmp = compare_replay_runs(catalog_ok, catalog_broken)
    assert listed_cmp.same_stream_hash is True
    assert listed_cmp.error_count_delta == 2


def test_verify_registered_replay_run_artifacts(
    db_session: Session, tmp_path: Path
) -> None:
    replay, report, request = _seed_replay(db_session, prefix="VER")
    output = tmp_path / "run"
    result = write_replay_run_artifacts(
        replay,
        report,
        output,
        request=request,
        created_at=datetime(2024, 1, 10, tzinfo=UTC),
        resolve_git=False,
    )
    register_replay_run(db_session, result.manifest, base_path=output)
    integrity = verify_registered_replay_run(
        db_session, str(result.manifest.replay_id), output
    )
    assert integrity.ok is True
    assert integrity.recomputed_stream_hash == result.manifest.stream_hash
