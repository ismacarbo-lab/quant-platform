"""List registered simulation replay runs. No vendors or trading."""

from __future__ import annotations

import argparse
import json
import sys

from quant_platform.core.config import get_settings
from quant_platform.core.redact import redact_secret_text
from quant_platform.simulation.errors import SimulationError
from quant_platform.simulation.run_catalog import list_replay_runs
from quant_platform.simulation.run_types import build_replay_run_catalog_filters
from quant_platform.storage.database import create_db_engine, create_session_factory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="List replay-run catalog metadata from PostgreSQL."
    )
    parser.add_argument("--stream-hash", default=None)
    parser.add_argument(
        "--usable-only",
        action="store_true",
        help="Keep rows with is_usable=true.",
    )
    parser.add_argument(
        "--boundary-ok",
        action="store_true",
        help="Keep rows with boundary_ok=true.",
    )
    parser.add_argument("--source-type", default=None)
    parser.add_argument("--dataset-snapshot-id", default=None)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.is_research_mode:
        print("error: APP_MODE must be research", file=sys.stderr)
        return 1

    try:
        filters = build_replay_run_catalog_filters(
            stream_hash=args.stream_hash,
            usable_only=args.usable_only,
            boundary_ok=True if args.boundary_ok else None,
            source_type=args.source_type,
            dataset_snapshot_id=args.dataset_snapshot_id,
        )
    except SimulationError as exc:
        print(f"error: {exc} ({exc.code})", file=sys.stderr)
        return 1

    engine = create_db_engine(settings, connect_timeout_seconds=5)
    factory = create_session_factory(engine)
    session = factory()
    try:
        rows = list_replay_runs(session, filters)
    except Exception as exc:
        print(f"error: {redact_secret_text(str(exc))}", file=sys.stderr)
        return 1
    finally:
        session.close()
        engine.dispose()

    if args.as_json:
        print(json.dumps([row.as_mapping() for row in rows], indent=2, sort_keys=True))
        return 0

    print(f"mode={settings.app_mode.value}")
    print(f"count={len(rows)}")
    print("replay_id\tusable\tboundary\terrors\tevents\tsource\tstream_hash")
    for row in rows:
        usable = "yes" if row.is_usable else "no"
        boundary = "yes" if row.boundary_ok else "no"
        print(
            f"{row.replay_id}\t{usable}\t{boundary}\t{row.error_count}\t"
            f"{row.event_count}\t{row.source_type}\t{row.stream_hash}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
