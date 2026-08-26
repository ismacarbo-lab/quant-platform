"""Compare two registered backtest experiments. No vendors or trading."""

from __future__ import annotations

import argparse
import json
import sys

from quant_platform.backtest.errors import BacktestError
from quant_platform.backtest.experiment_catalog import (
    compare_catalog_backtest_experiments,
)
from quant_platform.core.config import get_settings
from quant_platform.core.redact import redact_secret_text
from quant_platform.storage.database import create_db_engine, create_session_factory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compare two registered backtest-experiment catalog rows. "
            "Not a strategy and not PnL."
        )
    )
    parser.add_argument("--left", required=True, help="Left experiment_id.")
    parser.add_argument("--right", required=True, help="Right experiment_id.")
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
        diff = compare_catalog_backtest_experiments(session, args.left, args.right)
    except BacktestError as exc:
        print(f"error: {exc} ({exc.code})", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"error: {redact_secret_text(str(exc))}", file=sys.stderr)
        return 1
    finally:
        session.close()
        engine.dispose()

    if args.as_json:
        print(
            json.dumps(diff.as_mapping(), indent=2, sort_keys=True, ensure_ascii=True)
        )
        return 0

    print(f"mode={settings.app_mode.value}")
    print(f"left={diff.experiment_a_id}")
    print(f"right={diff.experiment_b_id}")
    print(f"same_experiment_hash={str(diff.same_experiment_hash).lower()}")
    print(f"same_manifest_hash={str(diff.same_manifest_hash).lower()}")
    print(f"identical={str(diff.identical).lower()}")
    print(f"verdict={diff.verdict}")
    if not diff.items:
        print("differences=")
        return 0
    print("differences=" + ",".join(item.field for item in diff.items))
    for item in diff.items:
        print(f"{item.field}\t{item.code}\t{item.left or ''}\t{item.right or ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
