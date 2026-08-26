"""Check whether a registered NoOp backtest result is usable evidence."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from quant_platform.backtest.readiness import (
    evaluate_backtest_result_usability,
    usability_report_json,
)
from quant_platform.core.config import get_settings
from quant_platform.core.redact import redact_secret_text
from quant_platform.storage.database import create_db_engine, create_session_factory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate whether a registered dry-run backtest is usable research "
            "evidence. Does not run a strategy or compute PnL."
        )
    )
    parser.add_argument("--backtest-id", required=True, help="Catalog backtest_id.")
    parser.add_argument(
        "--base-dir",
        required=True,
        type=Path,
        help="Run folder, or a parent directory of run folders.",
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
        report = evaluate_backtest_result_usability(
            session, args.backtest_id, args.base_dir
        )
    except Exception as exc:
        print(f"error: {redact_secret_text(str(exc))}", file=sys.stderr)
        return 1
    finally:
        session.close()
        engine.dispose()

    if args.as_json:
        print(usability_report_json(report), end="\n")
        return 0 if report.usable_result else 1

    print(f"mode={settings.app_mode.value}")
    print(f"usable_result={str(report.usable_result).lower()}")
    print(f"backtest_id={report.backtest_id}")
    print(f"replay_id={report.replay_id or ''}")
    print(f"policy={report.policy_name or ''}")
    print(f"error_count={report.error_count}")
    print(f"warning_count={report.warning_count}")
    print(f"artifacts_ok={str(report.gate.artifacts_ok).lower()}")
    print(f"policy_output_ok={str(report.gate.policy_output_ok).lower()}")
    print(f"replay_registered={str(report.gate.replay_registered).lower()}")
    print(f"run_root={report.run_root or ''}")
    for issue in report.issues:
        print(f"{issue.severity}\t{issue.code}\t{issue.message}")
    return 0 if report.usable_result else 1


if __name__ == "__main__":
    raise SystemExit(main())
