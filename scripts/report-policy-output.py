"""Summarize research policy observations. No signals, orders, or PnL."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from quant_platform.backtest.observation_reports import (
    build_observation_report,
    observation_report_json,
)
from quant_platform.core.config import get_settings
from quant_platform.core.redact import redact_secret_text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Print a research observation report from policy_output.json. "
            "Does not emit signals or compute PnL."
        )
    )
    parser.add_argument(
        "--backtest-run-dir",
        required=True,
        type=Path,
        help="Directory containing policy_output.json.",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.is_research_mode:
        print("error: APP_MODE must be research", file=sys.stderr)
        return 1

    try:
        report = build_observation_report(args.backtest_run_dir)
    except Exception as exc:
        print(f"error: {redact_secret_text(str(exc))}", file=sys.stderr)
        return 1

    if args.as_json:
        print(observation_report_json(report), end="\n")
        return 0

    print(f"mode={settings.app_mode.value}")
    print(f"policy={report.policy_name or ''}")
    print(f"observations={report.observation_count}")
    print(f"warnings={report.warning_count}")
    print(f"errors={report.error_count}")
    print(f"unknown_events={report.unknown_event_count}")
    print(f"corrections={report.correction_count}")
    print(f"corporate_actions={report.corporate_action_count}")
    print(f"sessions={report.session_count}")
    print(f"policy_output_hash={report.policy_output_hash or ''}")
    for item in report.kinds:
        print(f"kind\t{item.kind}\t{item.count}")
    for item in report.severities:
        print(f"severity\t{item.severity}\t{item.count}")
    for issue in report.issues:
        print(f"{issue.severity}\t{issue.code}\t{issue.message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
