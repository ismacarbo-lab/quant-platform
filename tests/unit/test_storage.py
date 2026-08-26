"""Storage factory targets PostgreSQL without connecting to a live server."""

from __future__ import annotations

from quant_platform.core.config import Settings
from quant_platform.data.models import DailyBar, DataSource, IngestionRun, Instrument
from quant_platform.storage.database import (
    Base,
    create_db_engine,
    create_session_factory,
)


def test_base_registers_ingestion_tables_not_trading() -> None:
    names = set(Base.metadata.tables)
    assert {"data_sources", "instruments", "ingestion_runs", "daily_bars"} <= names
    assert {"raw_ingestion_records", "ingestion_errors"} <= names
    assert {"market_calendars", "market_sessions", "instrument_identifiers"} <= names
    assert {"exchanges", "corporate_actions", "dataset_snapshots"} <= names
    assert "simulation_replay_runs" in names
    assert "backtest_runs" in names
    assert "backtest_experiments" in names
    assert names.isdisjoint({"orders", "trades", "fills", "signals", "strategies"})
    assert {DailyBar.__tablename__, DataSource.__tablename__} <= names
    assert Instrument.__tablename__ in names
    assert IngestionRun.__tablename__ in names


def test_session_factory_uses_postgres_engine(research_settings: Settings) -> None:
    engine = create_db_engine(research_settings)
    try:
        factory = create_session_factory(engine)
        session = factory()
        try:
            bind = session.get_bind()
            assert bind.dialect.name == "postgresql"
        finally:
            session.close()
    finally:
        engine.dispose()
