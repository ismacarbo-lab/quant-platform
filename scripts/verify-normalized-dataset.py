"""Verify local normalization artifacts. Read-only; not trading."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from quant_platform.core.config import get_settings
from quant_platform.core.redact import redact_secret_text
from quant_platform.research.normalization import verify_normalization_artifacts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify local corporate-action normalization artifacts. "
            "Does not trade or call vendors."
        )
    )
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.is_research_mode:
        print("error: APP_MODE must be research", file=sys.stderr)
        return 1

    try:
        report = verify_normalization_artifacts(args.run_dir)
    except Exception as exc:
        print(f"error: {redact_secret_text(str(exc))}", file=sys.stderr)
        return 1

    blob = json.dumps(report.as_mapping(), indent=2, sort_keys=True, ensure_ascii=True)
    if "DATABASE_URL" in blob or "postgresql+psycopg://" in blob:
        print("error: normalization integrity leaked a database URL", file=sys.stderr)
        return 1
    if args.as_json:
        print(blob)
    else:
        print(f"mode={settings.app_mode.value}")
        print(f"ok={str(report.ok).lower()}")
        print(f"dataset_hash={report.dataset_hash or ''}")
        print(f"errors={report.error_count}")
        print(f"warnings={report.warning_count}")
        for issue in report.issues:
            print(f"{issue.severity}\t{issue.code}\t{issue.message}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
