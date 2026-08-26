"""Replay a point-in-time daily-bar dataset as ordered market events."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from quant_platform.core.config import get_settings
from quant_platform.core.redact import redact_secret_text
from quant_platform.research.errors import DatasetErrorCode, DatasetValidationError
from quant_platform.research.types import build_daily_bars_dataset_request
from quant_platform.simulation.errors import SimulationError
from quant_platform.simulation.replay import (
    create_daily_bar_replay,
    replay_daily_bars_snapshot,
)
from quant_platform.storage.database import create_db_engine, create_session_factory


def _parse_utc(value: str, *, field: str) -> datetime:
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise DatasetValidationError(
            f"{field} must be timezone-aware UTC (got naive {value!r})",
            code=DatasetErrorCode.NAIVE_TIMESTAMP,
        )
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Replay a PIT daily-bar dataset as ordered market events. Not a backtester."
        )
    )
    parser.add_argument(
        "--as-of", default=None, help="UTC instant, e.g. 2024-01-10T00:00:00Z"
    )
    parser.add_argument(
        "--start", default=None, help="Inclusive observation start (UTC)."
    )
    parser.add_argument("--end", default=None, help="Inclusive observation end (UTC).")
    parser.add_argument("--symbol", action="append", dest="symbols", default=None)
    parser.add_argument(
        "--exchange", action="append", dest="exchange_codes", default=None
    )
    parser.add_argument(
        "--asset-class", action="append", dest="asset_classes", default=None
    )
    parser.add_argument("--currency", default=None)
    parser.add_argument("--calendar", default=None, dest="calendar_code")
    parser.add_argument(
        "--require-open-session",
        action="store_true",
        help="Require --calendar and keep only open/half sessions.",
    )
    parser.add_argument(
        "--allow-unfiltered",
        action="store_true",
        help="Allow a query with no symbol/exchange/asset-class/currency filter.",
    )
    parser.add_argument(
        "--snapshot-dir",
        type=Path,
        default=None,
        help="Replay a local snapshot folder instead of querying PostgreSQL.",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.is_research_mode:
        print("error: APP_MODE must be research", file=sys.stderr)
        return 1

    try:
        if args.snapshot_dir is not None:
            result = replay_daily_bars_snapshot(args.snapshot_dir)
        else:
            as_of_raw = args.as_of
            start_raw = args.start
            end_raw = args.end
            if as_of_raw is None or start_raw is None or end_raw is None:
                print(
                    "error: --as-of, --start, and --end are required "
                    "unless --snapshot-dir",
                    file=sys.stderr,
                )
                return 1
            request = build_daily_bars_dataset_request(
                as_of=_parse_utc(as_of_raw, field="as_of"),
                start_time=_parse_utc(start_raw, field="start_time"),
                end_time=_parse_utc(end_raw, field="end_time"),
                symbols=args.symbols,
                exchange_codes=args.exchange_codes,
                asset_classes=args.asset_classes,
                currency=args.currency,
                calendar_code=args.calendar_code,
                require_open_session=args.require_open_session,
                allow_unfiltered=args.allow_unfiltered,
            )
            engine = create_db_engine(settings, connect_timeout_seconds=5)
            factory = create_session_factory(engine)
            session = factory()
            try:
                result = create_daily_bar_replay(session, request)
            finally:
                session.close()
                engine.dispose()
    except (DatasetValidationError, SimulationError) as exc:
        print(f"error: {exc} ({exc.code})", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"error: {redact_secret_text(str(exc))}", file=sys.stderr)
        return 1

    summary = result.summary
    if args.as_json:
        print(
            json.dumps(
                summary.as_mapping(), indent=2, sort_keys=True, ensure_ascii=True
            )
        )
        return 0

    print(f"mode={settings.app_mode.value}")
    print(f"replay_id={summary.replay_id}")
    print(f"source_type={summary.source_type}")
    print(f"event_count={summary.event_count}")
    print(f"bar_count={summary.bar_count}")
    print(f"instrument_count={summary.instrument_count}")
    first = (
        "" if summary.first_event_time is None else summary.first_event_time.isoformat()
    )
    last = (
        "" if summary.last_event_time is None else summary.last_event_time.isoformat()
    )
    print(f"first_event_time={first}")
    print(f"last_event_time={last}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
