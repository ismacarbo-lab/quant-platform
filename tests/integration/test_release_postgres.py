"""PostgreSQL research release-candidate checks. No trading tables."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from quant_platform.core.config import get_settings
from quant_platform.release.checks import run_research_release_checks
from quant_platform.release.constants import (
    EXPECTED_ALEMBIC_HEAD,
    EXPECTED_PUBLIC_TABLES,
)
from quant_platform.simulation.constructs import FORBIDDEN_TABLE_NAMES
from quant_platform.storage.database import list_public_tables

pytestmark = pytest.mark.postgres

_TRADING_TABLES = FORBIDDEN_TABLE_NAMES | {"portfolio"}


def test_alembic_head_matches_expected(postgres_engine: Engine) -> None:
    settings = get_settings()
    assert settings.is_research_mode is True
    with postgres_engine.connect() as connection:
        head = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar()
    assert head == EXPECTED_ALEMBIC_HEAD


def test_check_db_tables_have_no_trading(postgres_engine: Engine) -> None:
    tables = set(list_public_tables(postgres_engine))
    assert tables.isdisjoint(_TRADING_TABLES)
    assert tables <= EXPECTED_PUBLIC_TABLES
    for name in (
        "strategies",
        "signals",
        "orders",
        "portfolio",
        "trades",
        "fills",
    ):
        assert name not in tables


def test_release_check_with_database_passes(postgres_engine: Engine) -> None:
    settings = get_settings()
    assert settings.is_research_mode is True
    report = run_research_release_checks(
        settings=settings,
        skip_compose=True,
        skip_regression=True,
        require_db=True,
    )
    assert report.ok is True
    assert report.database_checked is True
    db_items = [item for item in report.checks if item.name == "database"]
    assert db_items
    assert db_items[0].status == "ok"
    assert "trading_tables=none" in db_items[0].message
    blob = str(report.as_mapping())
    assert "DATABASE_URL" not in blob
    assert "postgresql+psycopg://" not in blob
