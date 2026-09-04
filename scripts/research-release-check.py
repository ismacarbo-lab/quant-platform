"""Run research release-candidate checks. Not a trading or vendor client."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from quant_platform.core.config import get_settings
from quant_platform.core.redact import redact_secret_text
from quant_platform.release.checks import run_research_release_checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run research release-candidate checks. Does not trade, "
            "download data, or call vendors."
        )
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the release status report as JSON.",
    )
    parser.add_argument(
        "--skip-db",
        action="store_true",
        help="Do not ping PostgreSQL.",
    )
    parser.add_argument(
        "--require-db",
        action="store_true",
        help="Fail if PostgreSQL is unreachable.",
    )
    parser.add_argument(
        "--skip-compose",
        action="store_true",
        help="Do not run docker compose config.",
    )
    parser.add_argument(
        "--skip-regression",
        action="store_true",
        help="Do not run the policy regression matrix.",
    )
    parser.add_argument(
        "--skip-normalization-regression",
        action="store_true",
        help="Do not run the normalization regression matrix.",
    )
    parser.add_argument(
        "--skip-data-contract-conformance",
        action="store_true",
        help="Do not run the data-contract conformance regression matrix.",
    )
    parser.add_argument(
        "--skip-data-contract-schema-compatibility",
        action="store_true",
        help="Do not compare live contract schemas against the baseline.",
    )
    parser.add_argument(
        "--skip-contract-payload-intake",
        action="store_true",
        help="Do not run the contract-payload intake regression matrix.",
    )
    parser.add_argument(
        "--matrix-path",
        type=Path,
        default=None,
        help="Override the policy regression matrix path.",
    )
    parser.add_argument(
        "--normalization-fixtures-dir",
        type=Path,
        default=None,
        help="Override the normalization regression fixtures directory.",
    )
    parser.add_argument(
        "--conformance-fixtures-dir",
        type=Path,
        default=None,
        help="Override the data-contract conformance fixtures directory.",
    )
    parser.add_argument(
        "--schema-baseline-file",
        type=Path,
        default=None,
        help="Override the data-contract schema baseline JSON.",
    )
    parser.add_argument(
        "--intake-fixtures-dir",
        type=Path,
        default=None,
        help="Override the contract-payload intake fixtures directory.",
    )
    args = parser.parse_args(argv)
    try:
        settings = get_settings()
        report = run_research_release_checks(
            settings=settings,
            matrix_path=args.matrix_path,
            skip_db=bool(args.skip_db),
            require_db=bool(args.require_db),
            skip_compose=bool(args.skip_compose),
            skip_regression=bool(args.skip_regression),
            skip_normalization_regression=bool(args.skip_normalization_regression),
            skip_data_contract_conformance=bool(args.skip_data_contract_conformance),
            skip_data_contract_schema_compatibility=bool(
                args.skip_data_contract_schema_compatibility
            ),
            skip_contract_payload_intake=bool(args.skip_contract_payload_intake),
            normalization_fixtures_dir=args.normalization_fixtures_dir,
            conformance_fixtures_dir=args.conformance_fixtures_dir,
            schema_baseline_file=args.schema_baseline_file,
            intake_fixtures_dir=args.intake_fixtures_dir,
        )
    except Exception as exc:
        print(redact_secret_text(str(exc)), file=sys.stderr)
        return 1
    blob = json.dumps(
        report.as_mapping(),
        indent=2,
        sort_keys=True,
        ensure_ascii=True,
    )
    if "DATABASE_URL" in blob or "postgresql+psycopg://" in blob:
        print("error: release report leaked a database URL", file=sys.stderr)
        return 1
    if args.json:
        print(blob)
    else:
        print(
            f"research release check: ok={str(report.ok).lower()} "
            f"errors={report.error_count} warnings={report.warning_count}"
        )
        print(
            f"  mode={report.app_mode} version={report.package_version} "
            f"alembic={report.alembic_head_expected}"
        )
        print(
            f"  policies={report.registered_policy_count} "
            f"regression_cases={report.regression_case_count}"
        )
        trading = "detected" if report.trading_constructs_detected else "none"
        ai_runtime = "detected" if report.ai_runtime_detected else "none"
        print(f"  trading_constructs={trading} ai_runtime={ai_runtime}")
        for item in report.checks:
            if item.status in {"error", "warning"}:
                print(f"  {item.status}: {item.name}: {item.message}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
