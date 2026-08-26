"""Verify a local dry-run backtest folder. No vendors or trading."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from quant_platform.backtest.integrity import (
    backtest_integrity_json,
    verify_backtest_artifacts,
)
from quant_platform.core.config import get_settings
from quant_platform.core.redact import redact_secret_text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify local backtest artifacts and hashes (read-only)."
    )
    parser.add_argument(
        "--run-dir",
        required=True,
        type=Path,
        help="Directory with manifest.json and summary.json.",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.is_research_mode:
        print("error: APP_MODE must be research", file=sys.stderr)
        return 1

    try:
        report = verify_backtest_artifacts(args.run_dir)
    except Exception as exc:
        print(f"error: {redact_secret_text(str(exc))}", file=sys.stderr)
        return 1

    if args.as_json:
        print(backtest_integrity_json(report), end="\n")
        return 0 if report.ok else 1

    print(f"mode={settings.app_mode.value}")
    print(f"ok={str(report.ok).lower()}")
    print(f"backtest_id={report.backtest_id or ''}")
    print(f"replay_id={report.replay_id or ''}")
    print(f"policy={report.policy_name or ''}")
    print(f"errors={report.error_count}")
    print(f"warnings={report.warning_count}")
    print(f"backtest_hash={report.backtest_hash or ''}")
    print(f"recomputed_backtest_hash={report.recomputed_backtest_hash or ''}")
    print(f"manifest_hash={report.manifest_hash or ''}")
    print(f"recomputed_manifest_hash={report.recomputed_manifest_hash or ''}")
    for issue in report.issues:
        print(f"{issue.severity}\t{issue.code}\t{issue.message}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
