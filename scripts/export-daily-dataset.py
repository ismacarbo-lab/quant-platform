"""Export a local research daily-bar dataset to CSV. No vendors or trading."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from quant_platform.core.config import get_settings
from quant_platform.core.redact import redact_secret_text
from quant_platform.research.datasets import (
    get_corporate_actions_for_dataset,
    get_daily_bars_dataset,
)
from quant_platform.research.errors import DatasetErrorCode, DatasetValidationError
from quant_platform.research.export import (
    write_corporate_actions_csv,
    write_daily_bars_csv,
)
from quant_platform.research.types import build_daily_bars_dataset_request
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
        description="Export a point-in-time daily-bar research dataset to CSV."
    )
    parser.add_argument(
        "--as-of", required=True, help="UTC instant, e.g. 2024-01-10T00:00:00Z"
    )
    parser.add_argument(
        "--start", required=True, help="Inclusive observation start (UTC)."
    )
    parser.add_argument("--end", required=True, help="Inclusive observation end (UTC).")
    parser.add_argument(
        "--output", required=True, type=Path, help="Destination CSV path."
    )
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
        "--corporate-actions-output",
        type=Path,
        default=None,
        help="Optional CSV of matching stored corporate actions (not applied).",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.is_research_mode:
        print("error: APP_MODE must be research", file=sys.stderr)
        return 1

    try:
        request = build_daily_bars_dataset_request(
            as_of=_parse_utc(args.as_of, field="as_of"),
            start_time=_parse_utc(args.start, field="start_time"),
            end_time=_parse_utc(args.end, field="end_time"),
            symbols=args.symbols,
            exchange_codes=args.exchange_codes,
            asset_classes=args.asset_classes,
            currency=args.currency,
            calendar_code=args.calendar_code,
            require_open_session=args.require_open_session,
            allow_unfiltered=args.allow_unfiltered,
        )
    except DatasetValidationError as exc:
        print(f"error: {exc} ({exc.code})", file=sys.stderr)
        return 1

    engine = create_db_engine(settings, connect_timeout_seconds=5)
    factory = create_session_factory(engine)
    session = factory()
    try:
        dataset = get_daily_bars_dataset(session, request)
        bar_count = write_daily_bars_csv(dataset, args.output)
        action_count = 0
        if args.corporate_actions_output is not None:
            actions = get_corporate_actions_for_dataset(session, request)
            action_count = write_corporate_actions_csv(
                actions, args.corporate_actions_output
            )
    except DatasetValidationError as exc:
        print(f"error: {exc} ({exc.code})", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"error: {redact_secret_text(str(exc))}", file=sys.stderr)
        return 1
    finally:
        session.close()
        engine.dispose()

    print(f"mode={settings.app_mode.value}")
    print(f"as_of={request.as_of.isoformat()}")
    print(f"bar_rows={bar_count}")
    print(f"output={args.output}")
    if args.corporate_actions_output is not None:
        print(f"corporate_action_rows={action_count}")
        print(f"corporate_actions_output={args.corporate_actions_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
