"""Print a lightweight research release status. No DB, no trading."""

from __future__ import annotations

import argparse
import json
import sys

from quant_platform.core.config import get_settings
from quant_platform.core.redact import redact_secret_text
from quant_platform.release.status import build_release_status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Print research release-candidate status without heavy checks. "
            "Does not ping PostgreSQL or run the policy matrix."
        )
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the status report as JSON.",
    )
    args = parser.parse_args(argv)
    try:
        settings = get_settings()
        if not settings.is_research_mode:
            print("APP_MODE must be research", file=sys.stderr)
            return 1
        report = build_release_status(settings=settings)
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
        print("error: status report leaked a database URL", file=sys.stderr)
        return 1
    if args.json:
        print(blob)
        return 0
    print(f"quant_platform {report.package_version} mode={report.app_mode}")
    print(f"alembic_head_expected={report.alembic_head_expected}")
    policy_names = ", ".join(report.registered_policy_names)
    print(f"policies={report.registered_policy_count} ({policy_names})")
    print(f"regression_cases={report.regression_case_count}")
    print("disabled=" + ",".join(report.capabilities.disabled))
    return 0


if __name__ == "__main__":
    sys.exit(main())
