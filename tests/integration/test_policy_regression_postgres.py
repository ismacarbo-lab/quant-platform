"""PostgreSQL checks for policy regression. Matrix itself does not use the DB."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from quant_platform.backtest.catalog import register_backtest_run
from quant_platform.backtest.engine import run_backtest_from_replay_run
from quant_platform.backtest.policy_registry import registered_policy_names
from quant_platform.backtest.types import ALLOWED_POLICY_NAMES, BacktestRequest
from quant_platform.core.config import get_settings
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


def _seed_replay(db_session: Session, tmp_path: Path):
    source = upsert_data_source(db_session, name=_unique("src"), vendor="local_csv")
    instrument = upsert_instrument(
        db_session, symbol=_unique("RG"), asset_class="equity"
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
    output = tmp_path / "rg"
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


def test_research_mode_and_no_trading_tables(postgres_engine: Engine) -> None:
    settings = get_settings()
    assert settings.is_research_mode is True
    tables = set(list_public_tables(postgres_engine))
    assert tables.isdisjoint(_TRADING_TABLES)
    assert registered_policy_names() == ALLOWED_POLICY_NAMES


def test_registered_policies_run_on_catalogued_replay(
    db_session: Session, tmp_path: Path
) -> None:
    settings = get_settings()
    assert settings.is_research_mode is True
    replay, replay_dir = _seed_replay(db_session, tmp_path)
    replay_id = str(replay.manifest.replay_id)
    for name in sorted(ALLOWED_POLICY_NAMES):
        result = run_backtest_from_replay_run(
            db_session,
            BacktestRequest(
                replay_id=replay_id,
                deterministic_id=True,
                policy_name=name,
            ),
            replay_dir,
            output_dir=tmp_path / name,
            created_at=datetime(2024, 1, 11, tzinfo=UTC),
            git_commit="deadbeef",
            resolve_git=False,
            research_mode=True,
        )
        assert result.manifest is not None
        register_backtest_run(db_session, result.manifest)
        assert result.summary.policy_name == name
        assert result.orders == ()
        assert result.fills == ()
        assert result.signals == ()
