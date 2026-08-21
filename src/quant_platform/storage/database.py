"""Engine and session factories for PostgreSQL.

Phase 0 does not define market-data or trading tables. Alembic is wired
to ``Base.metadata`` so future migrations have a single target.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from quant_platform.core.config import Settings, get_settings


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for research persistence."""


def create_db_engine(
    settings: Settings | None = None,
    *,
    connect_timeout_seconds: int | None = None,
) -> Engine:
    cfg = settings or get_settings()
    kwargs: dict[str, Any] = {
        "pool_pre_ping": True,
        "pool_size": 5,
        "max_overflow": 5,
    }
    if connect_timeout_seconds is not None:
        kwargs["connect_args"] = {"connect_timeout": connect_timeout_seconds}
    return create_engine(cfg.database_url, **kwargs)


def ping_database(engine: Engine) -> None:
    """Run ``SELECT 1``. Opens and closes a connection. Creates no tables."""
    with engine.connect() as connection:
        value = connection.execute(text("SELECT 1")).scalar()
        if value != 1:
            msg = f"PostgreSQL ping expected 1, got {value!r}"
            raise RuntimeError(msg)


def list_public_tables(engine: Engine) -> list[str]:
    """Return public-schema table names."""
    return sorted(inspect(engine).get_table_names())


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        class_=Session,
    )


def session_scope(
    session_factory: sessionmaker[Session],
) -> Generator[Session]:
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
