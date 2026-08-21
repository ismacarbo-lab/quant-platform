"""Alembic bronze and identity revision round-trips against PostgreSQL."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from quant_platform.core.config import clear_settings_cache
from quant_platform.storage.database import list_public_tables

pytestmark = pytest.mark.postgres

ROOT = Path(__file__).resolve().parents[2]

_BRONZE_TABLES = frozenset({"raw_ingestion_records", "ingestion_errors"})
_IDENTITY_TABLES = frozenset(
    {"market_calendars", "market_sessions", "instrument_identifiers"}
)
_SILVER_TABLES = frozenset(
    {"data_sources", "instruments", "ingestion_runs", "daily_bars"}
)


def test_bronze_revision_downgrade_and_upgrade(postgres_engine: Engine) -> None:
    clear_settings_cache()
    cfg = Config(str(ROOT / "alembic.ini"))
    try:
        command.downgrade(cfg, "0001_ingestion")
        inspect(postgres_engine).clear_cache()
        tables = set(list_public_tables(postgres_engine))
        assert tables.isdisjoint(_BRONZE_TABLES)
        assert tables.isdisjoint(_IDENTITY_TABLES)
        assert _SILVER_TABLES <= tables
    finally:
        command.upgrade(cfg, "head")
        inspect(postgres_engine).clear_cache()
    tables = set(list_public_tables(postgres_engine))
    assert _BRONZE_TABLES <= tables
    assert _SILVER_TABLES <= tables
    assert _IDENTITY_TABLES <= tables


def test_identity_revision_downgrade_and_upgrade(postgres_engine: Engine) -> None:
    clear_settings_cache()
    cfg = Config(str(ROOT / "alembic.ini"))
    try:
        command.downgrade(cfg, "0002_bronze")
        inspect(postgres_engine).clear_cache()
        tables = set(list_public_tables(postgres_engine))
        assert tables.isdisjoint(_IDENTITY_TABLES)
        assert _BRONZE_TABLES <= tables
        assert _SILVER_TABLES <= tables
    finally:
        command.upgrade(cfg, "head")
        inspect(postgres_engine).clear_cache()
    tables = set(list_public_tables(postgres_engine))
    assert _IDENTITY_TABLES <= tables
    assert _BRONZE_TABLES <= tables
