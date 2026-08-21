"""Ping local PostgreSQL using application settings.

Creates no tables and does not touch financial vendors.

    uv run python scripts/check-db.py
"""

from __future__ import annotations

import sys

from quant_platform.core.config import get_settings
from quant_platform.core.redact import redact_secret_text
from quant_platform.storage.database import (
    create_db_engine,
    list_public_tables,
    ping_database,
)

_ALLOWED_TABLES = frozenset(
    {
        "alembic_version",
        "data_sources",
        "instruments",
        "ingestion_runs",
        "daily_bars",
        "raw_ingestion_records",
        "ingestion_errors",
        "market_calendars",
        "market_sessions",
        "instrument_identifiers",
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
        try:
            ping_database(engine)
            tables = list_public_tables(engine)
        except Exception as exc:
            print(f"error: {redact_secret_text(str(exc))}", file=sys.stderr)
            return 1
    finally:
        engine.dispose()

    unexpected = [name for name in tables if name not in _ALLOWED_TABLES]
    trading = [name for name in tables if name in _TRADING_TABLES]
    print(f"mode={settings.app_mode.value}")
    print("ping=ok")
    print(f"tables={tables}")
    if trading:
        print(f"error: trading tables present {trading}", file=sys.stderr)
        return 1
    if unexpected:
        print(f"error: unexpected tables {unexpected}", file=sys.stderr)
        return 1
    print("trading_tables=none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
