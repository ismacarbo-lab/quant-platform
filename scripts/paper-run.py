"""Run the simulated paper-trading engine for the latest completed session.

Requires ``APP_MODE=paper`` (fictional money, explicit opt-in). With
``--fetch`` the latest market data is downloaded first. ``--replay-from``
builds a simulated track record from past sessions (flagged as replayed).
Schedule it once per day after the US close, e.g. with cron:

    30 23 * * 1-5  cd /home/isma/invest && APP_MODE=paper make paper-run
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from quant_platform.core.config import get_settings
from quant_platform.core.redact import redact_secret_text
from quant_platform.marketdata.providers import YFinanceMarketDataProvider
from quant_platform.marketdata.service import fetch_and_store_market_data
from quant_platform.marketdata.universe import resolve_universe
from quant_platform.paper.engine import (
    PaperAccountRunReport,
    PaperEngine,
    PaperEngineError,
)
from quant_platform.storage.database import create_db_engine, create_session_factory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fill pending paper orders, mark accounts to market and queue the "
            "next rebalance. Fictional cash only; no real broker."
        )
    )
    parser.add_argument(
        "--fetch",
        action="store_true",
        help="Download the latest market data before running.",
    )
    parser.add_argument(
        "--replay-from",
        type=date.fromisoformat,
        default=None,
        help="Replay past sessions from this date to build a track record.",
    )
    parser.add_argument(
        "--account",
        action="append",
        default=None,
        help="Only run these account names (repeatable).",
    )
    parser.add_argument("--json", action="store_true", help="Print the report as JSON.")
    args = parser.parse_args(argv)
    try:
        settings = get_settings()
    except Exception as exc:
        print(redact_secret_text(str(exc)), file=sys.stderr)
        return 1
    if not settings.is_paper_mode:
        print("APP_MODE must be paper to run the paper engine", file=sys.stderr)
        return 1
    engine = create_db_engine(settings, connect_timeout_seconds=5)
    factory = create_session_factory(engine)
    session = factory()
    try:
        if args.fetch:
            fetch_report = fetch_and_store_market_data(
                session,
                YFinanceMarketDataProvider(),
                resolve_universe(None),
                source_name=settings.market_data_source_name,
            )
            if not fetch_report.ok:
                print("warning: market data fetch had errors", file=sys.stderr)
        paper = PaperEngine(session, settings)
        accounts = None
        if args.account:
            accounts = []
            for name in args.account:
                account = paper.get_account(name)
                if account is None:
                    print(f"unknown paper account {name!r}", file=sys.stderr)
                    return 1
                accounts.append(account)
        report = paper.run_all(replay_from=args.replay_from, accounts=accounts)
        session.commit()
    except PaperEngineError as exc:
        session.rollback()
        print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        session.rollback()
        print(redact_secret_text(f"{type(exc).__name__}: {exc}"), file=sys.stderr)
        return 1
    finally:
        session.close()
        engine.dispose()
    blob = json.dumps(report.as_mapping(), indent=2, sort_keys=True)
    if "DATABASE_URL" in blob or "postgresql+psycopg://" in blob:
        print("error: report leaked a database URL", file=sys.stderr)
        return 1
    if args.json:
        print(blob)
    else:
        dates = report.session_dates
        if len(dates) == 1:
            span = dates[-1].isoformat()
        else:
            span = f"{dates[0].isoformat()}..{dates[-1].isoformat()}"
            span += f" ({len(dates)} sessions)"
        print(f"paper run: ok={str(report.ok).lower()} sessions={span}")
        latest: dict[str, PaperAccountRunReport] = {}
        for item in report.accounts:
            latest[item.account_name] = item
        for name in sorted(latest):
            item = latest[name]
            equity = "n/a" if item.equity is None else f"{float(item.equity):,.2f}"
            print(
                f"  {name:26s} {item.status:8s} equity={equity:>14s} "
                f"orders+{item.orders_created} fills+{item.fills_executed}"
                f"{' ' + item.message if item.message else ''}"
            )
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
