"""Verify a local research evidence bundle. Read-only; not trading."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from quant_platform.core.config import get_settings
from quant_platform.core.redact import redact_secret_text
from quant_platform.release.evidence_integrity import (
    evidence_integrity_json,
    verify_research_evidence_bundle,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify local research evidence-bundle artifacts and hashes. "
            "Does not trade or call vendors."
        )
    )
    parser.add_argument(
        "--bundle-dir",
        required=True,
        type=Path,
        help="Directory with evidence_manifest.json and companion files.",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.is_research_mode:
        print("error: APP_MODE must be research", file=sys.stderr)
        return 1

    try:
        report = verify_research_evidence_bundle(args.bundle_dir)
    except Exception as exc:
        print(f"error: {redact_secret_text(str(exc))}", file=sys.stderr)
        return 1

    blob = evidence_integrity_json(report)
    if "DATABASE_URL" in blob or "postgresql+psycopg://" in blob:
        print("error: evidence integrity leaked a database URL", file=sys.stderr)
        return 1
    if args.as_json:
        print(blob)
    else:
        print(f"mode={settings.app_mode.value}")
        print(f"ok={str(report.ok).lower()}")
        print(f"bundle_hash={report.bundle_hash or ''}")
        print(f"recomputed_bundle_hash={report.recomputed_bundle_hash or ''}")
        print(f"errors={report.error_count}")
        print(f"warnings={report.warning_count}")
        for issue in report.issues:
            print(f"{issue.severity}\t{issue.code}\t{issue.message}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
