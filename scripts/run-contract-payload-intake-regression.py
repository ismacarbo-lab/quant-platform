"""Run the offline contract-payload intake regression matrix."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from quant_platform.core.config import get_settings
from quant_platform.core.redact import redact_secret_text
from quant_platform.data.contracts.errors import VendorContractError
from quant_platform.data.contracts.intake_regression import (
    default_contract_payload_intake_dir,
    intake_regression_report_has_blocking_errors,
    run_contract_payload_intake_regression,
)
from quant_platform.data.contracts.intake_regression_artifacts import (
    write_intake_regression_artifacts,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the offline contract-payload intake regression matrix "
            "against golden fixtures. Compares hashes, issue codes, and "
            "counts only. Not a vendor client and not trading."
        )
    )
    parser.add_argument(
        "--fixtures-dir",
        type=Path,
        default=None,
        help=("Case directories. Defaults to tests/fixtures/contract_payload_intake."),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=(
            "Write contract_payload_intake_regression_report.json and "
            "contract_payload_intake_regression_actuals.json."
        ),
    )
    parser.add_argument(
        "--update-expected",
        action="store_true",
        help=(
            "Write actuals for human review. Does not rewrite expected.json. "
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
    fixtures_dir = args.fixtures_dir or default_contract_payload_intake_dir()
    try:
        report = run_contract_payload_intake_regression(fixtures_dir)
        if args.output_dir is not None:
            write_intake_regression_artifacts(
                report,
                args.output_dir,
                write_actuals=True,
            )
    except VendorContractError as exc:
        print(redact_secret_text(str(exc)), file=sys.stderr)
        return 1
    except OSError as exc:
        print(redact_secret_text(str(exc)), file=sys.stderr)
        return 1
    blob = json.dumps(
        report.as_mapping(),
        indent=2,
        sort_keys=True,
        ensure_ascii=True,
    )
    if "DATABASE_URL" in blob or "postgresql+psycopg://" in blob:
        print("error: intake regression leaked a database URL", file=sys.stderr)
        return 1
    if args.json:
        print(blob)
    else:
        print(
            f"contract payload intake regression: "
            f"{report.passed_count}/{report.case_count} "
            f"passed errors={report.error_count} hash={report.report_hash}"
        )
        if args.update_expected:
            print(
                "wrote actuals for review; expected.json files were not modified",
            )
    if intake_regression_report_has_blocking_errors(
        report,
        ignore_expected_drift=bool(args.update_expected),
    ):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
