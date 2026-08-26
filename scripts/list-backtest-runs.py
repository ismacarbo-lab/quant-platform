"""List registered dry-run backtest runs. No vendors or trading."""

from __future__ import annotations

import argparse
import json
import sys

from quant_platform.backtest.catalog import list_backtest_runs
from quant_platform.backtest.errors import BacktestError
from quant_platform.backtest.types import build_backtest_run_catalog_filters
from quant_platform.core.config import get_settings
from quant_platform.core.redact import redact_secret_text
from quant_platform.storage.database import create_db_engine, create_session_factory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="List backtest-run catalog metadata from PostgreSQL."
    )
    parser.add_argument("--replay-id", default=None)
    parser.add_argument("--stream-hash", default=None)
    parser.add_argument(
        "--usable-only",
        action="store_true",
        help="Keep rows with is_usable=true.",
    )
    parser.add_argument("--policy-name", default=None)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.is_research_mode:
        print("error: APP_MODE must be research", file=sys.stderr)
        return 1

    try:
        filters = build_backtest_run_catalog_filters(
            replay_id=args.replay_id,
            stream_hash=args.stream_hash,
            usable_only=args.usable_only,
            policy_name=args.policy_name,
        )
    except BacktestError as exc:
        print(f"error: {exc} ({exc.code})", file=sys.stderr)
        return 1

    engine = create_db_engine(settings, connect_timeout_seconds=5)
    factory = create_session_factory(engine)
    session = factory()
    try:
        rows = list_backtest_runs(session, filters)
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
    print(
        "backtest_id\tusable\tpolicy\terrors\tevents\t"
        "replay_id\tbacktest_hash\tpolicy_out"
    )
    for row in rows:
        usable = "yes" if row.is_usable else "no"
        policy_out = _short_hash(row.policy_output_hash or "")
        print(
            f"{row.backtest_id}\t{usable}\t{row.policy_name}\t{row.error_count}\t"
            f"{row.event_count}\t{row.replay_id}\t{_short_hash(row.backtest_hash)}\t"
            f"{policy_out}"
        )
    return 0


def _short_hash(value: str) -> str:
    prefix = "sha256:"
    if value.startswith(prefix) and len(value) > len(prefix) + 12:
        return value[: len(prefix) + 12] + "…"
    return value


if __name__ == "__main__":
    raise SystemExit(main())
