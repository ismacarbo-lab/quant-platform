"""Run a dry-run backtest from a ready replay run. No trading."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from quant_platform.backtest.catalog import register_backtest_run
from quant_platform.backtest.engine import run_backtest_from_replay_run
from quant_platform.backtest.errors import BacktestError
from quant_platform.backtest.types import BacktestRequest
from quant_platform.core.config import get_settings
from quant_platform.core.redact import redact_secret_text
from quant_platform.simulation.errors import SimulationError
from quant_platform.storage.database import create_db_engine, create_session_factory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Dry-run NoOpBacktestPolicy over a registered replay run. "
            "Not a strategy and not trading."
        )
    )
    parser.add_argument("--replay-id", required=True)
    parser.add_argument(
        "--replay-base-dir",
        type=Path,
        required=True,
        help="Replay-run folder or a parent of run folders.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Write summary.json and manifest.json.",
    )
    parser.add_argument(
        "--register",
        action="store_true",
        help="Store backtest metadata in PostgreSQL. Requires --output-dir.",
    )
    parser.add_argument(
        "--deterministic-id",
        action="store_true",
        help="Derive backtest_id from backtest_hash.",
    )
    parser.add_argument("--notes", default=None, help="Optional backtest note.")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.is_research_mode:
        print("error: APP_MODE must be research", file=sys.stderr)
        return 1
    if args.register and args.output_dir is None:
        print("error: --register requires --output-dir", file=sys.stderr)
        return 1

    request = BacktestRequest(
        replay_id=args.replay_id,
        deterministic_id=args.deterministic_id,
        notes=args.notes,
    )
    engine = create_db_engine(settings, connect_timeout_seconds=5)
    factory = create_session_factory(engine)
    session = factory()
    catalog_action: str | None = None
    try:
        result = run_backtest_from_replay_run(
            session,
            request,
            args.replay_base_dir,
            output_dir=args.output_dir,
        )
        if args.register:
            if result.manifest is None:
                print("error: --register requires --output-dir", file=sys.stderr)
                return 1
            registration = register_backtest_run(session, result.manifest)
            session.commit()
            catalog_action = registration.action
    except (BacktestError, SimulationError) as exc:
        session.rollback()
        print(f"error: {exc} ({exc.code})", file=sys.stderr)
        return 1
    except Exception as exc:
        session.rollback()
        print(f"error: {redact_secret_text(str(exc))}", file=sys.stderr)
        return 1
    finally:
        session.close()
        engine.dispose()

    if args.as_json:
        payload = {
            "ok": True,
            "summary": result.summary.as_mapping(),
            "catalog_action": catalog_action,
        }
        if result.manifest is not None:
            payload["manifest_hash"] = result.manifest.manifest_hash
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print(f"mode={settings.app_mode.value}")
    print(f"backtest_id={result.summary.backtest_id}")
    print(f"replay_id={result.summary.replay_id}")
    print(f"policy={result.summary.policy_name}")
    print(f"backtest_hash={result.summary.backtest_hash}")
    print(f"stream_hash={result.summary.stream_hash}")
    print(f"event_count={result.summary.event_count}")
    print(f"market_event_count={result.summary.market_event_count}")
    print(f"warning_count={result.summary.warning_count}")
    print(f"error_count={result.summary.error_count}")
    if catalog_action is not None:
        print(f"catalog={catalog_action}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
