"""Run a dry-run backtest experiment. Groups research runs; not a strategy."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from quant_platform.backtest.errors import BacktestError
from quant_platform.backtest.experiment_types import BacktestExperimentRequest
from quant_platform.backtest.experiments import run_backtest_experiment
from quant_platform.backtest.policy_registry import registered_policy_names
from quant_platform.core.config import get_settings
from quant_platform.core.redact import redact_secret_text
from quant_platform.simulation.errors import SimulationError
from quant_platform.storage.database import create_db_engine, create_session_factory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Group allowed dry-run backtests under one research experiment. "
            "Not a strategy and not trading."
        )
    )
    parser.add_argument("--experiment-name", required=True)
    parser.add_argument(
        "--replay-id",
        action="append",
        required=True,
        dest="replay_ids",
        help="Replay id to include. Repeatable.",
    )
    parser.add_argument(
        "--replay-base-dir",
        type=Path,
        required=True,
        help="Replay-run folder or a parent of run folders.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Write experiment_summary.json and member backtest folders.",
    )
    parser.add_argument(
        "--policy-name",
        default="noop",
        help=(
            "Registered research policy ("
            + ", ".join(sorted(registered_policy_names()))
            + "). Default: noop. Not a strategy."
        ),
    )
    parser.add_argument(
        "--policy-config-json",
        action="append",
        default=None,
        help="JSON object of policy config. Repeatable. Not a strategy payload.",
    )
    parser.add_argument(
        "--register",
        action="store_true",
        help="Store experiment metadata in PostgreSQL.",
    )
    parser.add_argument(
        "--deterministic-id",
        action="store_true",
        help="Derive experiment_id and member backtest_id values from hashes.",
    )
    parser.add_argument("--notes", default=None, help="Optional experiment note.")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.is_research_mode:
        print("error: APP_MODE must be research", file=sys.stderr)
        return 1

    configs: list[dict[str, object]] = []
    for raw in args.policy_config_json or []:
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError as exc:
            print(
                f"error: policy-config-json is not valid JSON ({exc})",
                file=sys.stderr,
            )
            return 1
        if not isinstance(loaded, dict):
            print("error: policy-config-json must be a JSON object", file=sys.stderr)
            return 1
        configs.append(loaded)

    try:
        request = BacktestExperimentRequest(
            experiment_name=args.experiment_name,
            replay_ids=tuple(args.replay_ids),
            policy_name=args.policy_name,
            policy_configs=tuple(configs),
            deterministic_ids=args.deterministic_id,
            notes=args.notes,
        )
    except BacktestError as exc:
        print(f"error: {exc} ({exc.code})", file=sys.stderr)
        return 1

    engine = create_db_engine(settings, connect_timeout_seconds=5)
    factory = create_session_factory(engine)
    session = factory()
    try:
        result = run_backtest_experiment(
            session,
            request,
            args.replay_base_dir,
            args.output_dir,
            register=args.register,
        )
        if args.register:
            session.commit()
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
        payload: dict[str, object] = {
            "ok": True,
            "summary": result.summary.as_mapping(),
            "registered": args.register,
        }
        if result.manifest is not None:
            payload["manifest_hash"] = result.manifest.manifest_hash
            payload["experiment_hash"] = result.manifest.experiment_hash
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print(f"mode={settings.app_mode.value}")
    print(f"experiment_id={result.summary.experiment_id}")
    print(f"experiment_name={result.summary.experiment_name}")
    print(f"policy={result.summary.policy_name}")
    print(f"experiment_hash={result.summary.experiment_hash}")
    print(f"member_count={result.summary.member_count}")
    print(f"usable_count={result.summary.usable_count}")
    print(f"warning_count={result.summary.warning_count}")
    print(f"error_count={result.summary.error_count}")
    if result.manifest is not None:
        print(f"manifest_hash={result.manifest.manifest_hash}")
    if args.register:
        print("catalog=registered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
