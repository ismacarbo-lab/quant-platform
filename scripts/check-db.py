"""Ping local PostgreSQL using application settings.

Creates no tables and does not touch financial vendors. Intended for
Phase 0.1 runtime verification:

    uv run python scripts/check-db.py
"""

from __future__ import annotations

import sys

from quant_platform.core.config import get_settings
from quant_platform.storage.database import (
    create_db_engine,
    list_public_tables,
    ping_database,
)

_ALLOWED_INFRA_TABLES = frozenset({"alembic_version"})


def main() -> int:
    settings = get_settings()
    if not settings.is_research_mode:
        print("error: APP_MODE must be research", file=sys.stderr)
        return 1
    if not settings.database_url.startswith("postgresql"):
        print("error: DATABASE_URL must be PostgreSQL", file=sys.stderr)
        return 1

    engine = create_db_engine(settings, connect_timeout_seconds=5)
    try:
        ping_database(engine)
        tables = list_public_tables(engine)
    finally:
        engine.dispose()

    unexpected = [name for name in tables if name not in _ALLOWED_INFRA_TABLES]
    print(f"mode={settings.app_mode.value}")
    print("ping=ok")
    print(f"tables={tables}")
    if unexpected:
        print(f"error: unexpected tables {unexpected}", file=sys.stderr)
        return 1
    print("domain_tables=none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
