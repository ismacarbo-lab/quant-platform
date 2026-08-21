"""List registered research dataset snapshots. No vendors or trading."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime

from quant_platform.core.config import get_settings
from quant_platform.core.redact import redact_secret_text
from quant_platform.research.catalog import list_dataset_snapshots
from quant_platform.research.catalog_types import build_dataset_snapshot_catalog_filters
from quant_platform.research.errors import DatasetErrorCode, DatasetValidationError
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
        description="List dataset snapshot catalog metadata from PostgreSQL."
    )
    parser.add_argument("--content-hash", default=None)
    parser.add_argument("--snapshot-id", default=None)
    parser.add_argument("--manifest-hash", default=None)
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--as-of-from", default=None)
    parser.add_argument("--as-of-to", default=None)
    parser.add_argument(
        "--usable-only",
        action="store_true",
        help="Keep rows with is_usable=true (reproducible and error_count=0).",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.is_research_mode:
        print("error: APP_MODE must be research", file=sys.stderr)
        return 1

    try:
        filters = build_dataset_snapshot_catalog_filters(
            snapshot_id=args.snapshot_id,
            content_hash=args.content_hash,
            manifest_hash=args.manifest_hash,
            symbol=args.symbol,
            as_of_from=(
                _parse_utc(args.as_of_from, field="as_of_from")
                if args.as_of_from
                else None
            ),
            as_of_to=(
                _parse_utc(args.as_of_to, field="as_of_to") if args.as_of_to else None
            ),
            usable_only=args.usable_only,
        )
    except DatasetValidationError as exc:
        print(f"error: {exc} ({exc.code})", file=sys.stderr)
        return 1

    engine = create_db_engine(settings, connect_timeout_seconds=5)
    factory = create_session_factory(engine)
    session = factory()
    try:
        rows = list_dataset_snapshots(session, filters)
    except Exception as exc:
        print(f"error: {redact_secret_text(str(exc))}", file=sys.stderr)
        return 1
    finally:
        session.close()
        engine.dispose()

    if args.as_json:
        print(json.dumps([row.as_mapping() for row in rows], indent=2))
        return 0

    print(f"mode={settings.app_mode.value}")
    print(f"count={len(rows)}")
    print("snapshot_id\tusable\terrors\trows\tas_of\tcontent_hash")
    for row in rows:
        usable = "yes" if row.is_usable else "no"
        print(
            f"{row.snapshot_id}\t{usable}\t{row.error_count}\t"
            f"{row.row_count}\t{row.as_of.isoformat()}\t{row.content_hash}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
