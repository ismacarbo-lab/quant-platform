"""Verify registered research snapshots against local folders. Read-only."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from quant_platform.core.config import get_settings
from quant_platform.core.redact import redact_secret_text
from quant_platform.research.catalog_integrity import (
    integrity_report_json,
    verify_catalog,
)
from quant_platform.research.errors import DatasetValidationError
from quant_platform.storage.database import create_db_engine, create_session_factory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify catalog snapshot metadata against local artifact folders."
    )
    parser.add_argument(
        "--base-dir",
        required=True,
        type=Path,
        help="Snapshot folder, or a parent directory of snapshot folders.",
    )
    parser.add_argument("--snapshot-id", default=None)
    parser.add_argument(
        "--usable-only",
        action="store_true",
        help="Verify only catalog rows with is_usable=true.",
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
        report = verify_catalog(
            session,
            args.base_dir,
            snapshot_id=args.snapshot_id,
            usable_only=args.usable_only,
        )
    except DatasetValidationError as exc:
        print(f"error: {exc} ({exc.code})", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"error: {redact_secret_text(str(exc))}", file=sys.stderr)
        return 1
    finally:
        session.close()
        engine.dispose()

    if args.as_json:
        print(integrity_report_json(report), end="")
        return 0 if report.ok else 1

    print(f"mode={settings.app_mode.value}")
    print(f"ok={str(report.ok).lower()}")
    print(f"entry_count={report.entry_count}")
    print(f"verified_count={report.verified_count}")
    print(f"errors={report.error_count}")
    print(f"warnings={report.warning_count}")
    for item in report.reports:
        status = "ok" if item.ok else "broken"
        print(f"{item.snapshot_id or ''}\t{status}\terrors={item.error_count}")
        for issue in item.issues:
            print(f"  {issue.severity}\t{issue.code}\t{issue.message}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
