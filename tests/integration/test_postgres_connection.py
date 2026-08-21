"""Optional PostgreSQL runtime checks. Skip if the database is down."""

from __future__ import annotations

import pytest
from sqlalchemy.engine import Engine

from quant_platform.api.app import create_app
from quant_platform.core.config import Settings
from quant_platform.storage.database import list_public_tables, ping_database

_ALLOWED_TABLES = frozenset(
    {
        "alembic_version",
        "data_sources",
        "instruments",
        "ingestion_runs",
        "daily_bars",
    }
)
_TRADING_TABLES = frozenset(
    {
        "trades",
        "orders",
        "fills",
        "signals",
        "strategies",
        "positions",
    }
)

pytestmark = pytest.mark.postgres


def test_select_one_against_postgres(postgres_engine: Engine) -> None:
    ping_database(postgres_engine)


def test_no_trading_tables(postgres_engine: Engine) -> None:
    tables = set(list_public_tables(postgres_engine))
    assert tables.isdisjoint(_TRADING_TABLES)
    assert tables <= _ALLOWED_TABLES


def test_health_still_works_without_querying_db(
    live_settings: Settings, postgres_engine: Engine
) -> None:
    from fastapi.testclient import TestClient

    client = TestClient(create_app(live_settings))
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["mode"] == "research"
    ping_database(postgres_engine)
