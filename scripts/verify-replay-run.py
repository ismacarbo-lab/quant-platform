"""Verify a local simulation replay run. No vendors or trading."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from quant_platform.core.config import get_settings
from quant_platform.core.redact import redact_secret_text
from quant_platform.simulation.run_integrity import (
    replay_run_integrity_json,
    verify_replay_run_artifacts,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify local replay-run artifacts and hashes (read-only)."
    )
    parser.add_argument(
        "--run-dir",
        required=True,
        type=Path,
        help=(
            "Directory with manifest.json, events.jsonl, audit.json, and summary.json."
        ),
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.is_research_mode:
        print("error: APP_MODE must be research", file=sys.stderr)
        return 1

    try:
        report = verify_replay_run_artifacts(args.run_dir)
    except Exception as exc:
        print(f"error: {redact_secret_text(str(exc))}", file=sys.stderr)
        return 1

    if args.as_json:
        print(replay_run_integrity_json(report), end="\n")
        return 0 if report.ok else 1

    print(f"mode={settings.app_mode.value}")
    print(f"ok={str(report.ok).lower()}")
    print(f"replay_id={report.replay_id or ''}")
    print(f"errors={report.error_count}")
    print(f"warnings={report.warning_count}")
    print(f"stream_hash={report.stream_hash or ''}")
    print(f"recomputed_stream_hash={report.recomputed_stream_hash or ''}")
    print(f"manifest_hash={report.manifest_hash or ''}")
    print(f"recomputed_manifest_hash={report.recomputed_manifest_hash or ''}")
    print(f"event_count={report.event_count if report.event_count is not None else ''}")
    print(
        "jsonl_event_count="
        f"{report.jsonl_event_count if report.jsonl_event_count is not None else ''}"
    )
    for issue in report.issues:
        print(f"{issue.severity}\t{issue.code}\t{issue.message}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
