"""Download real daily market data (Yahoo Finance) into the PIT store.

Writes to PostgreSQL by default (use --dry-run to plan only). Incremental:
only the days after the last stored session are fetched, with a small
overlap to detect vendor restatements.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from quant_platform.core.config import get_settings
from quant_platform.core.redact import redact_secret_text
from quant_platform.marketdata.providers import (
    MarketDataProvider,
    RecordedMarketDataProvider,
    YFinanceMarketDataProvider,
)
from quant_platform.marketdata.service import fetch_and_store_market_data
from quant_platform.marketdata.universe import DEFAULT_HISTORY_START, resolve_universe
from quant_platform.storage.database import create_db_engine, create_session_factory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch daily bars and dividends for the ETF universe from Yahoo "
            "Finance and store them point-in-time through contract intake."
        )
    )
    parser.add_argument(
        "--symbols",
        nargs="*",
        default=None,
        help="Symbols to fetch (default: the ETF universe).",
    )
    parser.add_argument(
        "--include-crypto",
        action="store_true",
        help="Also fetch the optional BTC-USD series.",
    )
    parser.add_argument(
        "--start",
        type=date.fromisoformat,
        default=DEFAULT_HISTORY_START,
        help="History start date for a first load (ISO date).",
    )
    parser.add_argument(
        "--end",
        type=date.fromisoformat,
        default=None,
        help="Last session date to fetch (default: today).",
    )
    parser.add_argument(
        "--full-refresh",
        action="store_true",
        help="Re-fetch the whole history; differing bars become corrections.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Download and plan only; do not write PostgreSQL.",
    )
    parser.add_argument(
        "--recorded-dir",
        type=Path,
        default=None,
        help="Offline mode: read <SYMBOL>.csv fixtures instead of Yahoo.",
    )
    parser.add_argument("--json", action="store_true", help="Print the report as JSON.")
    args = parser.parse_args(argv)
    try:
        settings = get_settings()
    except Exception as exc:
        print(redact_secret_text(str(exc)), file=sys.stderr)
        return 1
    if not settings.is_research_mode:
        print("APP_MODE must be research or paper", file=sys.stderr)
        return 1
    provider: MarketDataProvider
    if args.recorded_dir is not None:
        provider = RecordedMarketDataProvider(args.recorded_dir)
    else:
        provider = YFinanceMarketDataProvider()
    instruments = resolve_universe(args.symbols, include_optional=args.include_crypto)
    engine = create_db_engine(settings, connect_timeout_seconds=5)
    factory = create_session_factory(engine)
    session = factory()
    try:
        report = fetch_and_store_market_data(
            session,
            provider,
            instruments,
            source_name=settings.market_data_source_name,
            start=args.start,
            end=args.end,
            write_db=not args.dry_run,
            full_refresh=args.full_refresh,
        )
    except Exception as exc:
        session.rollback()
        print(redact_secret_text(str(exc)), file=sys.stderr)
        return 1
    finally:
        session.close()
        engine.dispose()
    blob = json.dumps(report.as_mapping(), indent=2, sort_keys=True, ensure_ascii=True)
    if "DATABASE_URL" in blob or "postgresql+psycopg://" in blob:
        print("error: report leaked a database URL", file=sys.stderr)
        return 1
    if args.json:
        print(blob)
    else:
        mode = "dry_run" if args.dry_run else "write_db"
        print(
            f"market data fetch: ok={str(report.ok).lower()} mode={mode} "
            f"source={report.source_name} symbols={len(report.symbols)} "
            f"inserted_bars={report.inserted_daily_bars} "
            f"inserted_dividends={report.inserted_corporate_actions}"
        )
        for item in report.symbols:
            payload = item.payload
            last = payload.last_session if payload is not None else None
            detail = f" error={item.error}" if item.error else ""
            bars = item.inserted_daily_bars
            dividends = item.inserted_corporate_actions
            print(
                f"  {item.symbol:8s} {item.status:11s} "
                f"bars+{bars} div+{dividends} last={last}{detail}"
            )
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
