"""Write an aggregated experiment research report. No PnL or orders."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from quant_platform.backtest.errors import BacktestError
from quant_platform.backtest.experiment_catalog import get_backtest_experiment_by_id
from quant_platform.backtest.experiment_integrity import resolve_experiment_directory
from quant_platform.backtest.experiment_readiness import (
    evaluate_backtest_experiment_usability,
)
from quant_platform.backtest.experiment_report_artifacts import (
    write_backtest_experiment_report_artifacts,
)
from quant_platform.backtest.experiment_reports import (
    build_research_report_from_catalog,
    load_member_observation_reports,
)
from quant_platform.backtest.experiments import members_from_experiment_summary
from quant_platform.core.config import get_settings
from quant_platform.core.redact import redact_secret_text
from quant_platform.storage.database import create_db_engine, create_session_factory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build a research observation aggregate for a backtest experiment. "
            "Does not emit signals or compute PnL."
        )
    )
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument(
        "--base-dir",
        required=True,
        type=Path,
        help="Experiment folder, or a parent directory of experiment folders.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Write experiment_research_report.json (and usability JSON).",
    )
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
        entry = get_backtest_experiment_by_id(session, args.experiment_id)
        if entry is None:
            print("error: experiment_id is not registered", file=sys.stderr)
            return 1
        root = resolve_experiment_directory(args.base_dir, args.experiment_id)
        if root is None:
            print("error: experiment directory was not found", file=sys.stderr)
            return 1
        members = members_from_experiment_summary(entry.summary)
        observations = load_member_observation_reports(root, members)
        report = build_research_report_from_catalog(
            entry,
            observation_reports=observations,
            members=members,
        )
        usability = evaluate_backtest_experiment_usability(
            session, args.experiment_id, root
        )
        if args.output_dir is not None:
            write_backtest_experiment_report_artifacts(
                report, args.output_dir, usability=usability
            )
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
            json.dumps(report.as_mapping(), indent=2, sort_keys=True, ensure_ascii=True)
        )
        return 0

    print(f"mode={settings.app_mode.value}")
    print(f"experiment_id={report.experiment_id}")
    print(f"experiment_name={report.experiment_name}")
    print(f"policy={report.policy_name}")
    print(f"member_count={report.member_count}")
    print(f"usable_count={report.usable_count}")
    print(f"warning_count={report.warning_count}")
    print(f"error_count={report.error_count}")
    print(f"observations={report.observations.observation_count}")
    print(f"unknown_events={report.observations.unknown_event_count}")
    print(f"experiment_hash={report.experiment_hash}")
    print(f"report_hash={report.report_hash}")
    print(f"experiment_usable={str(usability.experiment_usable).lower()}")
    for item in report.observations.kinds:
        print(f"kind\t{item.kind}\t{item.count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
