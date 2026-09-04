"""Check vendor-agnostic schema compatibility against a baseline. Offline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from quant_platform.core.config import get_settings
from quant_platform.core.redact import redact_secret_text
from quant_platform.data.contracts.errors import VendorContractError
from quant_platform.data.contracts.schema_compatibility import (
    check_schema_compatibility_against_baseline,
)
from quant_platform.data.contracts.schema_export import (
    build_contract_schema_bundle,
    default_schema_baseline_path,
    write_contract_schema_bundle,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compare the live vendor-agnostic contract schemas against the "
            "pinned baseline. Does not download data, call vendors, or "
            "compute returns."
        )
    )
    parser.add_argument(
        "--baseline-file",
        type=Path,
        default=None,
        help=(
            "Pinned schema bundle JSON. Defaults to "
            "tests/fixtures/data_contract_schemas/current_baseline.json."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the compatibility report as JSON.",
    )
    parser.add_argument(
        "--write-current",
        type=Path,
        default=None,
        help="Optional directory for the live schema bundle artifacts.",
    )
    parser.add_argument(
        "--fail-on-potentially-breaking",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Exit 1 when the report is potentially_breaking (default true).",
    )
    args = parser.parse_args(argv)
    try:
        settings = get_settings()
    except Exception as exc:
        print(redact_secret_text(str(exc)), file=sys.stderr)
        return 1
    if not settings.is_research_mode:
        print("APP_MODE must be research", file=sys.stderr)
        return 1
    try:
        current = build_contract_schema_bundle()
        if args.write_current is not None:
            write_contract_schema_bundle(args.write_current, bundle=current)
        baseline = args.baseline_file or default_schema_baseline_path()
        report = check_schema_compatibility_against_baseline(
            baseline_file=baseline,
            current=current,
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
        print(
            "error: compatibility report leaked a database URL",
            file=sys.stderr,
        )
        return 1
    if args.json:
        print(blob)
    else:
        print(
            "data contract schema compatibility: "
            f"status={report.compatibility_status} "
            f"issues={report.issue_count} hash={report.report_hash}"
        )
    if args.fail_on_potentially_breaking and not report.ok:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
