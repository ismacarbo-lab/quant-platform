"""PostgreSQL research-policy backtest metadata. No trading tables."""

from __future__ import annotations

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
    get_backtest_run_by_id,
    register_backtest_run,
)
from quant_platform.backtest.compare import (
    BacktestRunDiffVerdict,
    diff_catalog_backtest_runs,
)
from quant_platform.backtest.engine import run_backtest_from_replay_run
from quant_platform.backtest.readiness import evaluate_backtest_result_usability
from quant_platform.backtest.types import BacktestRequest
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


def _run(
    db_session: Session,
    replay_dir: Path,
    replay_id: str,
    output_dir: Path,
    *,
    policy_name: str = "noop",
    policy_config: dict[str, object] | None = None,
    created_at: datetime | None = None,
):
    result = run_backtest_from_replay_run(
        db_session,
        BacktestRequest(
            replay_id=replay_id,
            deterministic_id=False,
            policy_name=policy_name,
            policy_config=policy_config,
        ),
        replay_dir,
        output_dir=output_dir,
        created_at=created_at or datetime(2024, 1, 11, tzinfo=UTC),
        git_commit="deadbeef",
        resolve_git=False,
        research_mode=True,
    )
    assert result.manifest is not None
    register_backtest_run(db_session, result.manifest)
    return result


def test_policy_metadata_revision(postgres_engine: Engine) -> None:
    clear_settings_cache()
    cfg = Config(str(ROOT / "alembic.ini"))
    try:
        command.downgrade(cfg, "0007_backtest_runs")
        inspect(postgres_engine).clear_cache()
        columns = {
            col["name"] for col in inspect(postgres_engine).get_columns("backtest_runs")
        }
        assert "policy_config" not in columns
        assert "policy_output_hash" not in columns
    finally:
        command.upgrade(cfg, "head")
        inspect(postgres_engine).clear_cache()
    columns = {
        col["name"] for col in inspect(postgres_engine).get_columns("backtest_runs")
    }
    assert {"policy_config", "policy_output_hash"} <= columns
    tables = set(list_public_tables(postgres_engine))
    assert tables.isdisjoint(_TRADING_TABLES)


def test_noop_and_event_counting_runs(
    db_session: Session, tmp_path: Path, postgres_engine: Engine
) -> None:
    settings = get_settings()
    assert settings.is_research_mode is True
    replay, replay_dir = _seed_ready_replay(db_session, tmp_path, prefix="NO")
    replay_id = str(replay.manifest.replay_id)
    noop = _run(db_session, replay_dir, replay_id, tmp_path / "noop")
    counting = _run(
        db_session,
        replay_dir,
        replay_id,
        tmp_path / "count",
        policy_name="event_counting",
        created_at=datetime(2024, 1, 12, tzinfo=UTC),
    )
    assert noop.summary.policy_name == "noop"
    assert counting.summary.policy_name == "event_counting"
    assert noop.summary.policy_output_hash
    assert counting.summary.policy_output_hash != noop.summary.policy_output_hash
    assert (tmp_path / "noop" / "policy_output.json").is_file()
    assert (tmp_path / "count" / "policy_output.json").is_file()
    assert noop.manifest is not None
    assert "policy_output_hash" in noop.manifest.as_mapping()
    loaded = get_backtest_run_by_id(db_session, str(noop.summary.backtest_id))
    assert loaded is not None
    assert loaded.policy_config == {}
    assert loaded.policy_output_hash == noop.summary.policy_output_hash
    report = evaluate_backtest_result_usability(
        db_session, str(noop.summary.backtest_id), tmp_path / "noop"
    )
    assert report.usable_result is True
    tables = set(list_public_tables(postgres_engine))
    assert tables.isdisjoint(_TRADING_TABLES)


def test_comparison_detects_policy_config_change(
    db_session: Session, tmp_path: Path
) -> None:
    replay, replay_dir = _seed_ready_replay(db_session, tmp_path, prefix="CF")
    replay_id = str(replay.manifest.replay_id)
    left = _run(db_session, replay_dir, replay_id, tmp_path / "a")
    right = _run(
        db_session,
        replay_dir,
        replay_id,
        tmp_path / "b",
        policy_config={"note": "window-b"},
        created_at=datetime(2024, 6, 1, tzinfo=UTC),
    )
    diff = diff_catalog_backtest_runs(
        db_session,
        str(left.summary.backtest_id),
        str(right.summary.backtest_id),
    )
    assert diff.verdict == BacktestRunDiffVerdict.DIFFERENT.value
    assert "policy_config" in {item.field for item in diff.items}
    assert diff.same_policy_output_hash is False
