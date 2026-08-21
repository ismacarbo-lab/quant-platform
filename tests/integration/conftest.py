"""PostgreSQL fixtures for integration tests."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from quant_platform.core.config import Settings, clear_settings_cache
from quant_platform.core.redact import redact_secret_text
from quant_platform.storage.database import (
    create_db_engine,
    create_session_factory,
    ping_database,
)

ROOT = Path(__file__).resolve().parents[2]


def _upgrade_head() -> None:
    clear_settings_cache()
    cfg = Config(str(ROOT / "alembic.ini"))
    command.upgrade(cfg, "head")


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
        if os.environ.get("QUANT_PLATFORM_REQUIRE_POSTGRES") == "1":
            raise
        pytest.skip(f"PostgreSQL is not reachable: {redact_secret_text(str(exc))}")
    try:
        _upgrade_head()
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def db_session(postgres_engine: Engine) -> Iterator[Session]:
    factory = create_session_factory(postgres_engine)
    session = factory()
    try:
        yield session
        session.rollback()
    finally:
        session.close()
