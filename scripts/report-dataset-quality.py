"""Print a research dataset quality report. No vendors or trading."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from quant_platform.core.config import get_settings
from quant_platform.core.redact import redact_secret_text
from quant_platform.research.errors import DatasetErrorCode, DatasetValidationError
from quant_platform.research.quality import (
    get_dataset_quality_report,
    write_dataset_quality_json,
)
from quant_platform.research.quality_types import build_dataset_quality_request
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
        description="Diagnose point-in-time research dataset quality."
    )
    parser.add_argument(
        "--as-of", required=True, help="UTC instant, e.g. 2025-01-02T00:00:00Z"
    )
    parser.add_argument(
        "--start", required=True, help="Inclusive observation start (UTC)."
    )
    parser.add_argument("--end", required=True, help="Inclusive observation end (UTC).")
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
        help="Require --calendar on the request (does not hide closed-session bars).",
    )
    parser.add_argument(
        "--allow-unfiltered",
        action="store_true",
        help="Allow a query with no symbol/exchange/asset-class/currency filter.",
    )
    parser.add_argument(
        "--strict-calendar",
        action="store_true",
        help="Treat bars on dates without a session row as errors.",
    )
    parser.add_argument(
        "--long-gap-open-sessions",
        type=int,
        default=5,
        help="Warn when this many consecutive open sessions lack bars.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional JSON report path.",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.is_research_mode:
        print("error: APP_MODE must be research", file=sys.stderr)
        return 1

    try:
        request = build_dataset_quality_request(
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
        )
    except DatasetValidationError as exc:
        print(f"error: {exc} ({exc.code})", file=sys.stderr)
        return 1

    engine = create_db_engine(settings, connect_timeout_seconds=5)
    factory = create_session_factory(engine)
    session = factory()
    try:
        report = get_dataset_quality_report(session, request)
        if args.output is not None:
            write_dataset_quality_json(report, args.output)
    except DatasetValidationError as exc:
        print(f"error: {exc} ({exc.code})", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"error: {redact_secret_text(str(exc))}", file=sys.stderr)
        return 1
    finally:
        session.close()
        engine.dispose()

    ratio = report.coverage.coverage_ratio
    print(f"mode={settings.app_mode.value}")
    print(f"as_of={report.as_of.isoformat()}")
    print(f"start={report.start_time.isoformat()}")
    print(f"end={report.end_time.isoformat()}")
    print(f"rows={report.total_rows}")
    print(f"instruments={report.instrument_count}")
    print(f"errors={report.error_count}")
    print(f"warnings={report.warning_count}")
    print(f"infos={report.info_count}")
    print(f"coverage_ratio={ratio if ratio is not None else 'n/a'}")
    print(f"corporate_actions={len(report.corporate_actions)}")
    print(f"ingestion_runs={len(report.ingestion_runs)}")
    if args.output is not None:
        print(f"output={args.output}")
    for issue in report.issues:
        when = (
            issue.observation_time.date().isoformat()
            if issue.observation_time is not None
            else "-"
        )
        symbol = issue.symbol or "-"
        print(
            f"{issue.severity.upper()}\t{issue.code}\t{symbol}\t{when}\t{issue.message}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
