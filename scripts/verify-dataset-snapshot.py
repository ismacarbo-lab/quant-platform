"""Verify a local research dataset snapshot. No database, vendors, or trading."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from quant_platform.core.config import get_settings
from quant_platform.core.redact import redact_secret_text
from quant_platform.research.catalog_integrity import (
    integrity_report_json,
    verify_snapshot_artifacts,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify local snapshot artifacts and hashes (read-only)."
    )
    parser.add_argument(
        "--snapshot-dir",
        required=True,
        type=Path,
        help="Directory containing manifest.json, daily_bars.csv, quality.json.",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.is_research_mode:
        print("error: APP_MODE must be research", file=sys.stderr)
        return 1

    try:
        report = verify_snapshot_artifacts(args.snapshot_dir)
    except Exception as exc:
        print(f"error: {redact_secret_text(str(exc))}", file=sys.stderr)
        return 1

    if args.as_json:
        print(integrity_report_json(report), end="")
        return 0 if report.ok else 1

    print(f"mode={settings.app_mode.value}")
    print(f"ok={str(report.ok).lower()}")
    print(f"snapshot_id={report.snapshot_id or ''}")
    print(f"errors={report.error_count}")
    print(f"warnings={report.warning_count}")
    print(f"content_hash={report.content_hash or ''}")
    print(f"recomputed_content_hash={report.recomputed_content_hash or ''}")
    print(f"quality_hash={report.quality_hash or ''}")
    print(f"recomputed_quality_hash={report.recomputed_quality_hash or ''}")
    print(f"manifest_hash={report.manifest_hash or ''}")
    print(f"recomputed_manifest_hash={report.recomputed_manifest_hash or ''}")
    for issue in report.issues:
        print(f"{issue.severity}\t{issue.code}\t{issue.message}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
