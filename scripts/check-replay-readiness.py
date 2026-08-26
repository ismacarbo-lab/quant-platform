"""Check whether a registered replay run is ready for future backtesting."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from quant_platform.core.config import get_settings
from quant_platform.core.redact import redact_secret_text
from quant_platform.simulation.readiness import (
    evaluate_replay_run_readiness,
    readiness_report_json,
)
from quant_platform.storage.database import create_db_engine, create_session_factory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate backtest readiness for a registered replay run. "
            "Does not run a backtest."
        )
    )
    parser.add_argument("--replay-id", required=True, help="Catalog replay_id.")
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
        report = evaluate_replay_run_readiness(session, args.replay_id, args.base_dir)
    except Exception as exc:
        print(f"error: {redact_secret_text(str(exc))}", file=sys.stderr)
        return 1
    finally:
        session.close()
        engine.dispose()

    if args.as_json:
        print(readiness_report_json(report), end="\n")
        return 0 if report.ready_for_backtest else 1

    print(f"mode={settings.app_mode.value}")
    print(f"ready_for_backtest={str(report.ready_for_backtest).lower()}")
    print(f"replay_id={report.replay_id}")
    print(f"error_count={report.error_count}")
    print(f"warning_count={report.warning_count}")
    print(
        "boundary_ok="
        f"{'' if report.boundary_ok is None else str(report.boundary_ok).lower()}"
    )
    print(f"stream_hash={report.stream_hash or ''}")
    print(f"artifacts_ok={str(report.gate.artifacts_ok).lower()}")
    print(f"run_root={report.run_root or ''}")
    for status in report.artifacts:
        exists = "yes" if status.exists else "no"
        print(f"artifact\t{status.name}\t{status.path}\t{exists}")
    for issue in report.issues:
        print(f"{issue.severity}\t{issue.code}\t{issue.message}")
    return 0 if report.ready_for_backtest else 1


if __name__ == "__main__":
    raise SystemExit(main())
