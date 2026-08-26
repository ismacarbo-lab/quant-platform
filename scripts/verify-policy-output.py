"""Verify local policy_output.json. No writes, vendors, or trading."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from quant_platform.backtest.policy_output_integrity import (
    policy_output_verification_json,
    verify_policy_output,
)
from quant_platform.core.config import get_settings
from quant_platform.core.redact import redact_secret_text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify policy_output.json hashes and observation constraints."
    )
    parser.add_argument(
        "--backtest-run-dir",
        required=True,
        type=Path,
        help="Directory containing policy_output.json.",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.is_research_mode:
        print("error: APP_MODE must be research", file=sys.stderr)
        return 1

    try:
        report = verify_policy_output(args.backtest_run_dir)
    except Exception as exc:
        print(f"error: {redact_secret_text(str(exc))}", file=sys.stderr)
        return 1

    if args.as_json:
        print(policy_output_verification_json(report), end="\n")
        return 0 if report.ok else 1

    print(f"mode={settings.app_mode.value}")
    print(f"ok={str(report.ok).lower()}")
    print(f"status={report.status}")
    print(f"policy={report.policy_name or ''}")
    print(f"errors={report.error_count}")
    print(f"warnings={report.warning_count}")
    count = "" if report.observation_count is None else str(report.observation_count)
    print(f"observations={count}")
    print(f"stored_hash={report.stored_hash or ''}")
    print(f"recomputed_hash={report.recomputed_hash or ''}")
    for issue in report.issues:
        print(f"{issue.severity}\t{issue.code}\t{issue.message}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
