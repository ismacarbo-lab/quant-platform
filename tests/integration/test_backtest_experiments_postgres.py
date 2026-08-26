"""PostgreSQL backtest experiment catalog. No trading tables."""

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

from quant_platform.backtest.errors import BacktestError, BacktestErrorCode
from quant_platform.backtest.experiment_catalog import (
    compare_catalog_backtest_experiments,
    get_backtest_experiment_by_id,
    list_backtest_experiments,
    register_backtest_experiment,
)
from quant_platform.backtest.experiment_integrity import (
    verify_backtest_experiment_artifacts,
)
from quant_platform.backtest.experiment_types import (
    EXPERIMENT_VERDICT_DIFFERENT,
    EXPERIMENT_VERDICT_IDENTICAL,
    BacktestExperimentRequest,
    build_backtest_experiment_catalog_filters,
)
from quant_platform.backtest.experiments import run_backtest_experiment
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
_TRADING_TABLES = frozenset(
    {
        "trades",
        "orders",
        "fills",
        "signals",
        "strategies",
        "positions",
        "portfolio",
    }
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


def _seed_ready_replay(db_session: Session, tmp_path: Path, *, prefix: str = "PL"):
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


def test_experiment_revision_upgrade_downgrade(postgres_engine: Engine) -> None:
    clear_settings_cache()
    cfg = Config(str(ROOT / "alembic.ini"))
    try:
        command.downgrade(cfg, "0008_backtest_policy_metadata")
        inspect(postgres_engine).clear_cache()
        tables = set(list_public_tables(postgres_engine))
        assert "backtest_experiments" not in tables
        assert "backtest_runs" in tables
    finally:
        command.upgrade(cfg, "head")
        inspect(postgres_engine).clear_cache()
    tables = set(list_public_tables(postgres_engine))
    assert "backtest_experiments" in tables
    assert tables.isdisjoint(_TRADING_TABLES)


def test_run_experiment_with_one_and_two_replays(
    db_session: Session, tmp_path: Path, postgres_engine: Engine
) -> None:
    settings = get_settings()
    assert settings.is_research_mode is True
    first, first_dir = _seed_ready_replay(db_session, tmp_path, prefix="E1")
    second, _second_dir = _seed_ready_replay(db_session, tmp_path, prefix="E2")
    one = run_backtest_experiment(
        db_session,
        BacktestExperimentRequest(
            experiment_name="single-replay-noop",
            replay_ids=(str(first.manifest.replay_id),),
            policy_name="noop",
            deterministic_ids=True,
        ),
        tmp_path,
        tmp_path / "exp-one",
        created_at=datetime(2024, 1, 11, tzinfo=UTC),
        git_commit="deadbeef",
        resolve_git=False,
        research_mode=True,
    )
    two = run_backtest_experiment(
        db_session,
        BacktestExperimentRequest(
            experiment_name="two-replay-noop",
            replay_ids=(
                str(first.manifest.replay_id),
                str(second.manifest.replay_id),
            ),
            policy_name="noop",
            deterministic_ids=True,
        ),
        tmp_path,
        tmp_path / "exp-two",
        created_at=datetime(2024, 1, 11, tzinfo=UTC),
        git_commit="deadbeef",
        resolve_git=False,
        research_mode=True,
    )
    assert one.summary.member_count == 1
    assert two.summary.member_count == 2
    assert (tmp_path / "exp-one" / "experiment_manifest.json").is_file()
    assert (tmp_path / "exp-two" / "runs" / "0002" / "manifest.json").is_file()
    assert first_dir.is_dir()
    report = verify_backtest_experiment_artifacts(tmp_path / "exp-two")
    assert report.ok is True
    tables = set(list_public_tables(postgres_engine))
    assert tables.isdisjoint(_TRADING_TABLES)


def test_register_upsert_and_manifest_hash_conflict(
    db_session: Session, tmp_path: Path
) -> None:
    replay, _replay_dir = _seed_ready_replay(db_session, tmp_path, prefix="REG")
    request = BacktestExperimentRequest(
        experiment_name="register-noop",
        replay_ids=(str(replay.manifest.replay_id),),
        policy_name="noop",
        deterministic_ids=True,
        notes="first",
    )
    result = run_backtest_experiment(
        db_session,
        request,
        tmp_path,
        tmp_path / "exp-reg",
        register=True,
        created_at=datetime(2024, 1, 11, tzinfo=UTC),
        git_commit="deadbeef",
        resolve_git=False,
        research_mode=True,
    )
    assert result.manifest is not None
    loaded = get_backtest_experiment_by_id(db_session, result.summary.experiment_id)
    assert loaded is not None
    assert loaded.notes == "first"
    updated_manifest = replace(result.manifest, notes="second")
    registration = register_backtest_experiment(db_session, updated_manifest)
    assert registration.action == "update"
    reloaded = get_backtest_experiment_by_id(db_session, result.summary.experiment_id)
    assert reloaded is not None
    assert reloaded.notes == "second"
    other = replace(result.manifest, experiment_id=str(uuid4()))
    with pytest.raises(BacktestError) as exc:
        register_backtest_experiment(db_session, other)
    assert exc.value.code == BacktestErrorCode.CATALOG_CONFLICT


def test_list_and_compare_experiments(db_session: Session, tmp_path: Path) -> None:
    replay, _replay_dir = _seed_ready_replay(db_session, tmp_path, prefix="CMP")
    replay_id = str(replay.manifest.replay_id)
    left = run_backtest_experiment(
        db_session,
        BacktestExperimentRequest(
            experiment_name="compare-noop",
            replay_ids=(replay_id,),
            policy_name="noop",
            deterministic_ids=True,
        ),
        tmp_path,
        tmp_path / "exp-left",
        register=True,
        created_at=datetime(2024, 1, 11, tzinfo=UTC),
        git_commit="deadbeef",
        resolve_git=False,
        research_mode=True,
    )
    right = run_backtest_experiment(
        db_session,
        BacktestExperimentRequest(
            experiment_name="compare-counts",
            replay_ids=(replay_id,),
            policy_name="event_counting",
            deterministic_ids=True,
        ),
        tmp_path,
        tmp_path / "exp-right",
        register=True,
        created_at=datetime(2024, 1, 12, tzinfo=UTC),
        git_commit="deadbeef",
        resolve_git=False,
        research_mode=True,
    )
    listed = list_backtest_experiments(
        db_session,
        build_backtest_experiment_catalog_filters(experiment_name="compare-noop"),
    )
    assert len(listed) == 1
    usable = list_backtest_experiments(
        db_session,
        build_backtest_experiment_catalog_filters(usable_only=True),
    )
    assert {row.experiment_id for row in usable} >= {
        left.summary.experiment_id,
        right.summary.experiment_id,
    }
    by_policy = list_backtest_experiments(
        db_session,
        build_backtest_experiment_catalog_filters(policy_name="event_counting"),
    )
    assert [row.experiment_id for row in by_policy] == [right.summary.experiment_id]
    identical = compare_catalog_backtest_experiments(
        db_session, left.summary.experiment_id, left.summary.experiment_id
    )
    assert identical.verdict == EXPERIMENT_VERDICT_IDENTICAL
    different = compare_catalog_backtest_experiments(
        db_session, left.summary.experiment_id, right.summary.experiment_id
    )
    assert different.verdict == EXPERIMENT_VERDICT_DIFFERENT


def test_no_trading_tables_and_research_mode(postgres_engine: Engine) -> None:
    settings = get_settings()
    assert settings.is_research_mode is True
    inspect(postgres_engine).clear_cache()
    tables = set(list_public_tables(postgres_engine))
    assert "backtest_experiments" in tables
    assert "backtest_runs" in tables
    assert tables.isdisjoint(_TRADING_TABLES)
    assert "DATABASE_URL" not in str(tables)
