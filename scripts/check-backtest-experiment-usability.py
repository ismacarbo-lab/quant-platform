"""Check whether a registered backtest experiment is usable evidence."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from quant_platform.backtest.experiment_readiness import (
    evaluate_backtest_experiment_usability,
    experiment_usability_report_json,
)
from quant_platform.core.config import get_settings
from quant_platform.core.redact import redact_secret_text
from quant_platform.storage.database import create_db_engine, create_session_factory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate whether a registered backtest experiment is usable "
            "research evidence. Does not run a strategy or compute PnL."
        )
    )
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument(
        "--base-dir",
        required=True,
        type=Path,
        help="Experiment folder, or a parent directory of experiment folders.",
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
        report = evaluate_backtest_experiment_usability(
            session, args.experiment_id, args.base_dir
        )
    except Exception as exc:
        print(f"error: {redact_secret_text(str(exc))}", file=sys.stderr)
        return 1
    finally:
        session.close()
        engine.dispose()

    if args.as_json:
        print(experiment_usability_report_json(report), end="\n")
        return 0 if report.experiment_usable else 1

    print(f"mode={settings.app_mode.value}")
    print(f"experiment_usable={str(report.experiment_usable).lower()}")
    print(f"experiment_id={report.experiment_id}")
    print(f"member_count={report.member_count}")
    print(f"usable_count={report.usable_count}")
    print(f"error_count={report.error_count}")
    print(f"warning_count={report.warning_count}")
    for issue in report.issues:
        print(f"{issue.severity}\t{issue.code}\t{issue.message}")
    return 0 if report.experiment_usable else 1


if __name__ == "__main__":
    raise SystemExit(main())
