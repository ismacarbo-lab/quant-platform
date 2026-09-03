"""Compare two registered normalized datasets. No vendors or trading."""

from __future__ import annotations

import argparse
import json
import sys

from quant_platform.core.config import get_settings
from quant_platform.core.redact import redact_secret_text
from quant_platform.research.normalization import NormalizationError
from quant_platform.research.normalization.catalog import (
    compare_catalog_normalized_datasets,
)
from quant_platform.storage.database import create_db_engine, create_session_factory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compare two registered normalized-dataset catalog rows. "
            "Not a strategy and not PnL."
        )
    )
    parser.add_argument("--left", required=True, help="Left normalized_dataset_id.")
    parser.add_argument("--right", required=True, help="Right normalized_dataset_id.")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.is_research_mode:
        print("error: APP_MODE must be research", file=sys.stderr)
        return 1

    engine = create_db_engine(settings, connect_timeout_seconds=5)
    factory = create_session_factory(engine)
    session = factory()
    try:
        diff = compare_catalog_normalized_datasets(session, args.left, args.right)
    except NormalizationError as exc:
        print(f"error: {exc} ({exc.code})", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"error: {redact_secret_text(str(exc))}", file=sys.stderr)
        return 1
    finally:
        session.close()
        engine.dispose()

    blob = json.dumps(diff.as_mapping(), indent=2, sort_keys=True, ensure_ascii=True)
    if "DATABASE_URL" in blob or "postgresql+psycopg://" in blob:
        print("error: catalog compare leaked a database URL", file=sys.stderr)
        return 1
    if args.as_json:
        print(blob)
        return 0

    print(f"mode={settings.app_mode.value}")
    print(f"left={diff.left_id}")
    print(f"right={diff.right_id}")
    print(f"verdict={diff.verdict}")
    print(f"same_dataset_hash={str(diff.same_dataset_hash).lower()}")
    print(f"same_manifest_hash={str(diff.same_manifest_hash).lower()}")
    if not diff.differences:
        print("differences=")
        return 0
    print("differences=" + ",".join(diff.differences))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
