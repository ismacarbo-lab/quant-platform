"""FastAPI dependencies: settings, lazily created engine, per-request session."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from quant_platform.api.jobs import JobRegistry
from quant_platform.core.config import Settings
from quant_platform.storage.database import create_db_engine, create_session_factory


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_engine(request: Request) -> Engine:
    existing: Engine | None = getattr(request.app.state, "engine", None)
    if existing is not None:
        return existing
    settings: Settings = request.app.state.settings
    engine = create_db_engine(settings, connect_timeout_seconds=5)
    request.app.state.engine = engine
    request.app.state.session_factory = create_session_factory(engine)
    return engine


def get_session_factory(request: Request) -> sessionmaker[Session]:
    get_engine(request)
    factory: sessionmaker[Session] = request.app.state.session_factory
    return factory


def get_db(request: Request) -> Iterator[Session]:
    factory = get_session_factory(request)
    session = factory()
    try:
        yield session
        session.rollback()
    finally:
        session.close()


def get_jobs(request: Request) -> JobRegistry:
    jobs: JobRegistry = request.app.state.jobs
    return jobs
