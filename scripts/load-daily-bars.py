"""Load local daily-bar CSV into PostgreSQL. No vendor APIs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from quant_platform.core.config import get_settings
from quant_platform.core.redact import redact_secret_text
from quant_platform.data.csv_loader import CsvLoadError, load_daily_bars_csv
from quant_platform.data.models import IngestionRun, IngestionStatus
from quant_platform.data.repository import (
    create_ingestion_run,
    finish_ingestion_run,
    insert_daily_bars,
    upsert_data_source,
    upsert_instrument,
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
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.is_research_mode:
        print("error: APP_MODE must be research", file=sys.stderr)
        return 1

    try:
        drafts = load_daily_bars_csv(args.csv_path)
    except (CsvLoadError, OSError) as exc:
        print(f"error: {redact_secret_text(str(exc))}", file=sys.stderr)
        return 1

    engine = create_db_engine(settings, connect_timeout_seconds=5)
    factory = create_session_factory(engine)
    session = factory()
    inserted = 0
    run_id = None
    try:
        source = upsert_data_source(
            session, name=args.source, vendor=args.vendor, description="local CSV"
        )
        run = create_ingestion_run(
            session,
            source_id=source.id,
            run_metadata={"kind": "local_csv"},
        )
        session.commit()
        run_id = run.id
        instruments = {}
        for symbol in sorted({draft.symbol for draft in drafts}):
            instruments[symbol] = upsert_instrument(
                session,
                symbol=symbol,
                asset_class=args.asset_class,
                currency=args.currency,
                exchange=args.exchange,
            )
        inserted = insert_daily_bars(
            session,
            drafts=drafts,
            instruments_by_symbol=instruments,
            source_id=source.id,
            ingestion_run_id=run.id,
        )
        finish_ingestion_run(
            session,
            run,
            status=IngestionStatus.SUCCEEDED,
            row_count=inserted,
        )
        session.commit()
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
    print(f"symbols={sorted({draft.symbol for draft in drafts})}")
    print(f"parsed_rows={len(drafts)}")
    print(f"inserted_rows={inserted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
