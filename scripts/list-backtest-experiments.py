"""List registered dry-run backtest experiments. No vendors or trading."""

from __future__ import annotations

import argparse
import json
import sys

from quant_platform.backtest.errors import BacktestError
from quant_platform.backtest.experiment_catalog import list_backtest_experiments
from quant_platform.backtest.experiment_types import (
    build_backtest_experiment_catalog_filters,
)
from quant_platform.core.config import get_settings
from quant_platform.core.redact import redact_secret_text
from quant_platform.storage.database import create_db_engine, create_session_factory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="List backtest-experiment catalog metadata from PostgreSQL."
    )
    parser.add_argument("--experiment-name", default=None)
    parser.add_argument("--policy-name", default=None)
    parser.add_argument(
        "--usable-only",
        action="store_true",
        help="Keep rows where every member is usable and error_count is 0.",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.is_research_mode:
        print("error: APP_MODE must be research", file=sys.stderr)
        return 1

    try:
        filters = build_backtest_experiment_catalog_filters(
            experiment_name=args.experiment_name,
            policy_name=args.policy_name,
            usable_only=args.usable_only,
        )
    except BacktestError as exc:
        print(f"error: {exc} ({exc.code})", file=sys.stderr)
        return 1

    engine = create_db_engine(settings, connect_timeout_seconds=5)
    factory = create_session_factory(engine)
    session = factory()
    try:
        rows = list_backtest_experiments(session, filters)
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
        "experiment_id\tname\tpolicy\tmembers\tusable\terrors\twarnings\texperiment_hash"
    )
    for row in rows:
        print(
            f"{row.experiment_id}\t{row.experiment_name}\t{row.policy_name}\t"
            f"{row.member_count}\t{row.usable_count}\t{row.error_count}\t"
            f"{row.warning_count}\t{_short_hash(row.experiment_hash)}"
        )
    return 0


def _short_hash(value: str) -> str:
    prefix = "sha256:"
    if value.startswith(prefix) and len(value) > len(prefix) + 12:
        return value[: len(prefix) + 12] + "…"
    return value


if __name__ == "__main__":
    raise SystemExit(main())
