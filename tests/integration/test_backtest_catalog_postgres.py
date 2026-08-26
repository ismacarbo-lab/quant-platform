"""PostgreSQL backtest catalog: ready replay, register, list, compare."""

from __future__ import annotations

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

from quant_platform.backtest.catalog import (
    compare_backtest_runs,
    get_backtest_run_by_id,
    get_backtest_run_by_manifest_hash,
    list_backtest_runs,
    register_backtest_run,
)
from quant_platform.backtest.engine import run_backtest_from_replay_run
from quant_platform.backtest.errors import BacktestError, BacktestErrorCode
from quant_platform.backtest.types import (
    BacktestRequest,
    build_backtest_run_catalog_filters,
)
from quant_platform.core.config import clear_settings_cache, get_settings
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
from quant_platform.simulation.replay import create_daily_bar_replay
from quant_platform.simulation.run_catalog import register_replay_run
from quant_platform.storage.database import list_public_tables

pytestmark = pytest.mark.postgres

ROOT = Path(__file__).resolve().parents[2]
_BACKTEST_TABLES = frozenset({"backtest_runs"})
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


def _seed_ready_replay(db_session: Session, tmp_path: Path, *, prefix: str = "BT"):
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
    output = tmp_path / prefix.lower()
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
    return result, output


def test_backtest_revision_downgrade_and_upgrade(postgres_engine: Engine) -> None:
    clear_settings_cache()
    cfg = Config(str(ROOT / "alembic.ini"))
    try:
        command.downgrade(cfg, "0006_replay_runs")
        inspect(postgres_engine).clear_cache()
        tables = set(list_public_tables(postgres_engine))
        assert tables.isdisjoint(_BACKTEST_TABLES)
        assert "simulation_replay_runs" in tables
    finally:
        command.upgrade(cfg, "head")
        inspect(postgres_engine).clear_cache()
    tables = set(list_public_tables(postgres_engine))
    assert _BACKTEST_TABLES <= tables
    assert tables.isdisjoint(_TRADING_TABLES)


def test_run_backtest_from_ready_replay_and_register(
    db_session: Session, tmp_path: Path, postgres_engine: Engine
) -> None:
    settings = get_settings()
    assert settings.is_research_mode is True
    replay_result, replay_dir = _seed_ready_replay(db_session, tmp_path, prefix="RDY")
    request = BacktestRequest(
        replay_id=str(replay_result.manifest.replay_id),
        deterministic_id=True,
        notes="dry-run",
    )
    result = run_backtest_from_replay_run(
        db_session,
        request,
        replay_dir,
        output_dir=tmp_path / "backtest",
        created_at=datetime(2024, 1, 11, tzinfo=UTC),
        git_commit="deadbeef",
        resolve_git=False,
        research_mode=True,
    )
    assert result.orders == ()
    assert result.fills == ()
    assert result.signals == ()
    assert result.summary.event_count == replay_result.manifest.event_count
    assert result.summary.started_event_seen is True
    assert result.summary.finished_event_seen is True
    assert result.manifest is not None
    inserted = register_backtest_run(db_session, result.manifest)
    assert inserted.action == "insert"
    assert inserted.entry.is_usable is True
    assert inserted.entry.policy_name == "noop"
    loaded = get_backtest_run_by_id(db_session, str(result.summary.backtest_id))
    by_hash = get_backtest_run_by_manifest_hash(
        db_session, result.manifest.manifest_hash
    )
    assert loaded is not None and by_hash is not None
    assert loaded.backtest_id == by_hash.backtest_id
    tables = set(list_public_tables(postgres_engine))
    assert "backtest_runs" in tables
    assert tables.isdisjoint(_TRADING_TABLES)
    assert (tmp_path / "backtest" / "summary.json").is_file()
    assert (tmp_path / "backtest" / "manifest.json").is_file()
    assert (tmp_path / "backtest" / "events.jsonl").exists() is False


def test_run_backtest_fails_if_replay_not_ready(
    db_session: Session, tmp_path: Path
) -> None:
    replay_result, replay_dir = _seed_ready_replay(db_session, tmp_path, prefix="MISS")
    (replay_dir / "events.jsonl").unlink()
    request = BacktestRequest(replay_id=str(replay_result.manifest.replay_id))
    with pytest.raises(BacktestError) as exc:
        run_backtest_from_replay_run(
            db_session,
            request,
            replay_dir,
            research_mode=True,
        )
    assert exc.value.code == BacktestErrorCode.NOT_READY


def test_register_upserts_by_backtest_id(db_session: Session, tmp_path: Path) -> None:
    replay_result, replay_dir = _seed_ready_replay(db_session, tmp_path, prefix="UPS")
    request = BacktestRequest(
        replay_id=str(replay_result.manifest.replay_id),
        deterministic_id=True,
        notes="first",
    )
    result = run_backtest_from_replay_run(
        db_session,
        request,
        replay_dir,
        output_dir=tmp_path / "bt",
        created_at=datetime(2024, 1, 11, tzinfo=UTC),
        git_commit="deadbeef",
        resolve_git=False,
        research_mode=True,
    )
    assert result.manifest is not None
    first = register_backtest_run(db_session, result.manifest)
    assert first.action == "insert"
    updated = replace(result.manifest, notes="second")
    second = register_backtest_run(db_session, updated)
    assert second.action == "update"
    loaded = get_backtest_run_by_id(db_session, str(result.summary.backtest_id))
    assert loaded is not None
    assert loaded.notes == "second"


def test_register_same_manifest_hash_different_id_conflicts(
    db_session: Session, tmp_path: Path
) -> None:
    replay_result, replay_dir = _seed_ready_replay(db_session, tmp_path, prefix="CF")
    request = BacktestRequest(
        replay_id=str(replay_result.manifest.replay_id),
        deterministic_id=True,
    )
    result = run_backtest_from_replay_run(
        db_session,
        request,
        replay_dir,
        output_dir=tmp_path / "bt",
        created_at=datetime(2024, 1, 11, tzinfo=UTC),
        git_commit="deadbeef",
        resolve_git=False,
        research_mode=True,
    )
    assert result.manifest is not None
    register_backtest_run(db_session, result.manifest)
    other = replace(result.manifest, backtest_id=uuid4())
    with pytest.raises(BacktestError) as exc:
        register_backtest_run(db_session, other)
    assert exc.value.code == BacktestErrorCode.CATALOG_CONFLICT


def test_list_and_compare_backtest_runs(db_session: Session, tmp_path: Path) -> None:
    first_replay, first_dir = _seed_ready_replay(db_session, tmp_path, prefix="L1")
    second_replay, second_dir = _seed_ready_replay(db_session, tmp_path, prefix="L2")
    left = run_backtest_from_replay_run(
        db_session,
        BacktestRequest(
            replay_id=str(first_replay.manifest.replay_id),
            deterministic_id=True,
        ),
        first_dir,
        output_dir=tmp_path / "left",
        created_at=datetime(2024, 1, 11, tzinfo=UTC),
        git_commit="deadbeef",
        resolve_git=False,
        research_mode=True,
    )
    right = run_backtest_from_replay_run(
        db_session,
        BacktestRequest(
            replay_id=str(second_replay.manifest.replay_id),
            deterministic_id=True,
        ),
        second_dir,
        output_dir=tmp_path / "right",
        created_at=datetime(2024, 1, 11, tzinfo=UTC),
        git_commit="deadbeef",
        resolve_git=False,
        research_mode=True,
    )
    assert left.manifest is not None and right.manifest is not None
    register_backtest_run(db_session, left.manifest)
    register_backtest_run(db_session, right.manifest)
    listed = list_backtest_runs(
        db_session,
        build_backtest_run_catalog_filters(
            replay_id=str(first_replay.manifest.replay_id)
        ),
    )
    assert {item.backtest_id for item in listed} == {str(left.summary.backtest_id)}
    usable = list_backtest_runs(
        db_session, build_backtest_run_catalog_filters(usable_only=True)
    )
    usable_ids = {item.backtest_id for item in usable}
    assert str(left.summary.backtest_id) in usable_ids
    assert str(right.summary.backtest_id) in usable_ids
    by_policy = list_backtest_runs(
        db_session, build_backtest_run_catalog_filters(policy_name="noop")
    )
    assert {item.backtest_id for item in by_policy} >= {
        str(left.summary.backtest_id),
        str(right.summary.backtest_id),
    }
    comparison = compare_backtest_runs(left.manifest, right.manifest)
    assert comparison.same_replay_id is False
    assert comparison.same_policy_name is True
    catalog_left = get_backtest_run_by_id(db_session, str(left.summary.backtest_id))
    catalog_right = get_backtest_run_by_id(db_session, str(right.summary.backtest_id))
    assert catalog_left is not None and catalog_right is not None
    listed_cmp = compare_backtest_runs(catalog_left, catalog_right)
    assert listed_cmp.same_replay_id is False
