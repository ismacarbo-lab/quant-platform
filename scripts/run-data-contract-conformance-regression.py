"""Run the offline data-contract conformance regression matrix."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from quant_platform.core.config import get_settings
from quant_platform.core.redact import redact_secret_text
from quant_platform.data.contracts.conformance_regression import (
    conformance_regression_report_has_blocking_errors,
    default_data_contract_conformance_dir,
    run_data_contract_conformance_regression,
)
from quant_platform.data.contracts.conformance_regression_artifacts import (
    write_conformance_regression_artifacts,
)
from quant_platform.data.contracts.errors import VendorContractError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the vendor-agnostic data-contract conformance regression "
            "matrix against golden fixtures. Compares hashes, issue codes, "
            "and counts only. Not a vendor client and not trading."
        )
    )
    parser.add_argument(
        "--fixtures-dir",
        type=Path,
        default=None,
        help=(
            "Case directories. Defaults to tests/fixtures/data_contract_conformance."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=(
            "Write data_contract_conformance_regression_report.json and "
            "data_contract_conformance_regression_actuals.json."
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
    fixtures_dir = args.fixtures_dir or default_data_contract_conformance_dir()
    try:
        report = run_data_contract_conformance_regression(fixtures_dir)
        if args.output_dir is not None:
            write_conformance_regression_artifacts(
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
        print("error: conformance regression leaked a database URL", file=sys.stderr)
        return 1
    if args.json:
        print(blob)
    else:
        print(
            f"data contract conformance regression: "
            f"{report.passed_count}/{report.case_count} "
            f"passed errors={report.error_count} hash={report.report_hash}"
        )
        if args.update_expected:
            print(
                "wrote actuals for review; expected.json files were not modified",
            )
    if conformance_regression_report_has_blocking_errors(
        report,
        ignore_expected_drift=bool(args.update_expected),
    ):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
