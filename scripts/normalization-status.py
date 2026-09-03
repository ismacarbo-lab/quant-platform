"""Print normalization add-on status. No trading and no secrets."""

from __future__ import annotations

import argparse
import json
import sys

from quant_platform.core.config import get_settings
from quant_platform.core.redact import redact_secret_text
from quant_platform.research.normalization.status import build_normalization_status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Print corporate-action normalization add-on status. "
            "Does not ping PostgreSQL unless --check-db is set. Not trading."
        )
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument(
        "--check-db",
        action="store_true",
        help="Ping PostgreSQL and confirm normalized_datasets exists.",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.is_research_mode:
        print("error: APP_MODE must be research", file=sys.stderr)
        return 1

    try:
        report = build_normalization_status(check_db=bool(args.check_db))
    except Exception as exc:
        print(f"error: {redact_secret_text(str(exc))}", file=sys.stderr)
        return 1

    blob = json.dumps(report.as_mapping(), indent=2, sort_keys=True, ensure_ascii=True)
    if "DATABASE_URL" in blob or "postgresql+psycopg://" in blob:
        print("error: normalization status leaked a database URL", file=sys.stderr)
        return 1
    if args.as_json:
        print(blob)
        return 0 if report.ok else 1

    print(f"mode={report.app_mode}")
    print(f"capability_enabled={str(report.capability_enabled).lower()}")
    print(f"expected_alembic_head={report.expected_alembic_head}")
    print(f"expected_table={report.expected_table}")
    print(f"regression_case_count={report.regression_case_count}")
    print("adjustment_modes=" + ",".join(report.adjustment_modes))
    print(f"dividend_policy={report.dividend_policy}")
    print(f"database_checked={str(report.database_checked).lower()}")
    if report.database_checked:
        print(f"database_table_present={str(report.database_table_present).lower()}")
        print(f"database_alembic_head={report.database_alembic_head or ''}")
    print(f"ok={str(report.ok).lower()}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
