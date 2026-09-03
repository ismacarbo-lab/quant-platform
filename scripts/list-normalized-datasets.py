"""List registered normalized-dataset catalog metadata. No vendors or trading."""

from __future__ import annotations

import argparse
import json
import sys

from quant_platform.core.config import get_settings
from quant_platform.core.redact import redact_secret_text
from quant_platform.research.normalization import (
    NormalizationError,
    build_normalized_dataset_catalog_filters,
    list_normalized_datasets,
)
from quant_platform.storage.database import create_db_engine, create_session_factory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="List normalized-dataset catalog metadata from PostgreSQL."
    )
    parser.add_argument("--dataset-hash", default=None)
    parser.add_argument("--raw-dataset-hash", default=None)
    parser.add_argument("--adjustment-mode", default=None)
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
        filters = build_normalized_dataset_catalog_filters(
            dataset_hash=args.dataset_hash,
            raw_dataset_hash=args.raw_dataset_hash,
            adjustment_mode=args.adjustment_mode,
            usable_only=args.usable_only,
        )
    except NormalizationError as exc:
        print(f"error: {exc} ({exc.code})", file=sys.stderr)
        return 1

    engine = create_db_engine(settings, connect_timeout_seconds=5)
    factory = create_session_factory(engine)
    session = factory()
    try:
        rows = list_normalized_datasets(session, filters)
    except Exception as exc:
        print(f"error: {redact_secret_text(str(exc))}", file=sys.stderr)
        return 1
    finally:
        session.close()
        engine.dispose()

    if args.as_json:
        blob = json.dumps([row.as_mapping() for row in rows], indent=2)
        if "DATABASE_URL" in blob or "postgresql+psycopg://" in blob:
            print("error: catalog list leaked a database URL", file=sys.stderr)
            return 1
        print(blob)
        return 0

    print(f"mode={settings.app_mode.value}")
    print(f"count={len(rows)}")
    print("normalized_dataset_id\tusable\terrors\tbars\tas_of\tdataset_hash")
    for row in rows:
        usable = "yes" if row.is_usable else "no"
        print(
            f"{row.normalized_dataset_id}\t{usable}\t{row.error_count}\t"
            f"{row.bar_count}\t{row.as_of.isoformat()}\t{row.dataset_hash}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
