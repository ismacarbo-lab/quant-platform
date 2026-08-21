"""Load local daily-bar CSV into PostgreSQL. No vendor APIs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from quant_platform.core.config import get_settings
from quant_platform.core.redact import redact_secret_text
from quant_platform.data.csv_loader import CsvLoadError, ErrorMode, ensure_csv_readable
from quant_platform.data.ingest import ingest_daily_bars_csv
from quant_platform.data.models import IngestionRun, IngestionStatus
from quant_platform.data.repository import (
    create_ingestion_run,
    finish_ingestion_run,
    list_ingestion_errors,
    upsert_data_source,
)
from quant_platform.storage.database import create_db_engine, create_session_factory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ingest local daily OHLCV CSV for research (no vendors)."
    )
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--source", default="local_csv")
    parser.add_argument("--vendor", default="local_csv")
    parser.add_argument("--asset-class", default="equity")
    parser.add_argument("--currency", default=None)
    parser.add_argument("--exchange", default=None)
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop on the first invalid row (default: collect-errors).",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.is_research_mode:
        print("error: APP_MODE must be research", file=sys.stderr)
        return 1

    error_mode = ErrorMode.FAIL_FAST if args.fail_fast else ErrorMode.COLLECT_ERRORS
    try:
        ensure_csv_readable(args.csv_path)
    except (CsvLoadError, OSError) as exc:
        print(f"error: {redact_secret_text(str(exc))}", file=sys.stderr)
        return 1

    engine = create_db_engine(settings, connect_timeout_seconds=5)
    factory = create_session_factory(engine)
    session = factory()
    accepted = 0
    rejected = 0
    inserted = 0
    error_codes: list[str] = []
    run_id = None
    exit_code = 0
    try:
        source = upsert_data_source(
            session, name=args.source, vendor=args.vendor, description="local CSV"
        )
        run = create_ingestion_run(
            session,
            source_id=source.id,
            run_metadata={"kind": "local_csv", "error_mode": error_mode.value},
        )
        session.commit()
        run_id = run.id
        result = ingest_daily_bars_csv(
            session,
            args.csv_path,
            source=source,
            run=run,
            asset_class=args.asset_class,
            currency=args.currency,
            exchange=args.exchange,
            error_mode=error_mode,
        )
        accepted = result.accepted_count
        rejected = result.rejected_count
        inserted = result.inserted_bars
        status = IngestionStatus.FAILED if result.aborted else IngestionStatus.SUCCEEDED
        finish_ingestion_run(
            session,
            run,
            status=status,
            row_count=accepted + rejected,
            accepted_count=accepted,
            rejected_count=rejected,
        )
        session.commit()
        error_codes = [
            error.error_code
            for error in list_ingestion_errors(session, ingestion_run_id=run.id)
        ]
        if result.aborted:
            exit_code = 1
    except Exception as exc:
        session.rollback()
        if run_id is not None:
            failed = session.get(IngestionRun, run_id)
            if failed is not None:
                finish_ingestion_run(
                    session,
                    failed,
                    status=IngestionStatus.FAILED,
                    row_count=0,
                    error_message=redact_secret_text(str(exc)),
                )
                session.commit()
        print(f"error: {redact_secret_text(str(exc))}", file=sys.stderr)
        return 1
    finally:
        session.close()
        engine.dispose()

    print(f"mode={settings.app_mode.value}")
    print(f"source={args.source}")
    print(f"error_mode={error_mode.value}")
    print(f"accepted_count={accepted}")
    print(f"rejected_count={rejected}")
    print(f"inserted_rows={inserted}")
    if error_codes:
        print(f"error_codes={','.join(error_codes)}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
