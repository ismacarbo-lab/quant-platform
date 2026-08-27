"""Run the ResearchPolicy regression matrix. Not a strategy or trading tool."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from quant_platform.backtest.errors import BacktestError
from quant_platform.backtest.policy_regression import (
    default_policy_regression_matrix_path,
    regression_report_has_blocking_errors,
    run_policy_regression_matrix,
)
from quant_platform.backtest.policy_regression_artifacts import (
    write_policy_regression_artifacts,
)
from quant_platform.core.config import get_settings
from quant_platform.core.redact import redact_secret_text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the ResearchPolicy regression matrix against golden fixtures. "
            "Compares descriptive outputs only. Not a strategy and not trading."
        )
    )
    parser.add_argument(
        "--matrix-path",
        type=Path,
        default=None,
        help=(
            "Declarative matrix JSON. Defaults to "
            "tests/fixtures/policy_regression/matrix.json."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Write policy_regression_report.json and policy_regression_actuals.json.",
    )
    parser.add_argument(
        "--update-expected",
        action="store_true",
        help=(
            "Write actuals for human review. Does not rewrite matrix.json. "
            "Requires --output-dir. Hash drift is not a blocking error."
        ),
    )
    parser.add_argument("--json", action="store_true", help="Print the report as JSON.")
    args = parser.parse_args(argv)
    try:
        settings = get_settings()
    except Exception as exc:
        print(redact_secret_text(str(exc)), file=sys.stderr)
        return 1
    if not settings.is_research_mode:
        print("APP_MODE must be research", file=sys.stderr)
        return 1
    if args.update_expected and args.output_dir is None:
        print("--update-expected requires --output-dir", file=sys.stderr)
        return 2
    matrix_path = args.matrix_path or default_policy_regression_matrix_path()
    try:
        report = run_policy_regression_matrix(matrix_path)
        if args.output_dir is not None:
            write_policy_regression_artifacts(
                report,
                args.output_dir,
                write_actuals=True,
            )
    except BacktestError as exc:
        print(redact_secret_text(str(exc)), file=sys.stderr)
        return 1
    except OSError as exc:
        print(redact_secret_text(str(exc)), file=sys.stderr)
        return 1
    if args.json:
        print(
            json.dumps(
                report.as_mapping(),
                indent=2,
                sort_keys=True,
                ensure_ascii=True,
            )
        )
    else:
        print(
            f"policy regression: {report.passed_count}/{report.case_count} passed "
            f"errors={report.error_count} hash={report.report_hash}"
        )
        if args.update_expected:
            print(
                "wrote actuals for review; matrix.json was not modified",
            )
    if regression_report_has_blocking_errors(
        report,
        ignore_expected_drift=bool(args.update_expected),
    ):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
