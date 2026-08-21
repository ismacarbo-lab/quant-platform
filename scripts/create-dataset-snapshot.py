"""Create a local reproducible research dataset snapshot. No vendors or trading."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from quant_platform.core.config import get_settings
from quant_platform.core.redact import redact_secret_text
from quant_platform.research.errors import DatasetErrorCode, DatasetValidationError
from quant_platform.research.snapshot_types import build_dataset_snapshot_request
from quant_platform.research.snapshots import create_daily_bars_snapshot
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
            "Save a point-in-time research dataset snapshot (CSV + quality + manifest)."
        )
    )
    parser.add_argument(
        "--as-of", required=True, help="UTC instant, e.g. 2025-01-02T00:00:00Z"
    )
    parser.add_argument(
        "--start", required=True, help="Inclusive observation start (UTC)."
    )
    parser.add_argument("--end", required=True, help="Inclusive observation end (UTC).")
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="Local directory for CSV, quality JSON, and manifest.",
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
        help="Require --calendar on the dataset request.",
    )
    parser.add_argument(
        "--allow-unfiltered",
        action="store_true",
        help="Allow a query with no symbol/exchange/asset-class/currency filter.",
    )
    parser.add_argument(
        "--strict-calendar",
        action="store_true",
        help="Treat bars on dates without a session row as quality errors.",
    )
    parser.add_argument(
        "--long-gap-open-sessions",
        type=int,
        default=5,
        help="Quality warning threshold for consecutive missing open sessions.",
    )
    parser.add_argument("--notes", default=None, help="Optional snapshot note.")
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.is_research_mode:
        print("error: APP_MODE must be research", file=sys.stderr)
        return 1

    try:
        request = build_dataset_snapshot_request(
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
            strict_calendar=args.strict_calendar,
            long_gap_open_sessions=args.long_gap_open_sessions,
            notes=args.notes,
        )
    except DatasetValidationError as exc:
        print(f"error: {exc} ({exc.code})", file=sys.stderr)
        return 1

    engine = create_db_engine(settings, connect_timeout_seconds=5)
    factory = create_session_factory(engine)
    session = factory()
    try:
        result = create_daily_bars_snapshot(session, request, args.output_dir)
    except DatasetValidationError as exc:
        print(f"error: {exc} ({exc.code})", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"error: {redact_secret_text(str(exc))}", file=sys.stderr)
        return 1
    finally:
        session.close()
        engine.dispose()

    manifest = result.manifest
    print(f"mode={settings.app_mode.value}")
    print(f"snapshot_id={manifest.snapshot_id}")
    print(f"row_count={manifest.row_count}")
    print(f"instrument_count={manifest.instrument_count}")
    print(f"content_hash={manifest.content_hash}")
    print(f"quality_hash={manifest.quality_hash}")
    print(f"manifest_hash={manifest.manifest_hash}")
    print(f"manifest={result.manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
