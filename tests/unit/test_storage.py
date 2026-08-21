"""Storage factory targets PostgreSQL without connecting to a live server."""

from __future__ import annotations

from quant_platform.core.config import Settings
from quant_platform.storage.database import (
    Base,
    create_db_engine,
    create_session_factory,
)


def test_base_has_no_financial_tables() -> None:
    assert Base.metadata.tables == {}


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
