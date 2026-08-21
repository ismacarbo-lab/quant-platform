"""Optional PostgreSQL runtime checks. Skip if the database is down."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

from quant_platform.api.app import create_app
from quant_platform.core.config import Settings
from quant_platform.storage.database import (
    create_db_engine,
    list_public_tables,
    ping_database,
)

_ALLOWED_INFRA_TABLES = frozenset({"alembic_version"})
_DOMAIN_TABLES = frozenset(
    {
        "candles",
        "quotes",
        "trades",
        "orders",
        "fills",
        "signals",
        "strategies",
        "positions",
    }
)

pytestmark = pytest.mark.postgres


@pytest.fixture
def live_settings() -> Settings:
    return Settings()


@pytest.fixture
def postgres_engine(live_settings: Settings) -> Iterator[Engine]:
    engine = create_db_engine(live_settings, connect_timeout_seconds=3)
    try:
        ping_database(engine)
    except OperationalError as exc:
        engine.dispose()
        pytest.skip(f"PostgreSQL is not reachable: {exc}")
    yield engine
    engine.dispose()


def test_select_one_against_postgres(postgres_engine: Engine) -> None:
    ping_database(postgres_engine)


def test_no_domain_tables(postgres_engine: Engine) -> None:
    tables = set(list_public_tables(postgres_engine))
    assert tables.isdisjoint(_DOMAIN_TABLES)
    assert tables <= _ALLOWED_INFRA_TABLES


def test_health_still_works_without_querying_db(
    live_settings: Settings, postgres_engine: Engine
) -> None:
    client = TestClient(create_app(live_settings))
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["mode"] == "research"
    ping_database(postgres_engine)
