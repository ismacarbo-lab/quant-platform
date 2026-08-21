"""Engine and session factories for PostgreSQL.

Phase 0 does not define market-data or trading tables. Alembic is wired
to ``Base.metadata`` so future migrations have a single target.
"""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from quant_platform.core.config import Settings, get_settings


class Base(DeclarativeBase):
    """SQLAlchemy declarative base. Intentionally empty in Phase 0."""


def create_db_engine(settings: Settings | None = None) -> Engine:
    cfg = settings or get_settings()
    return create_engine(
        cfg.database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
    )


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
