"""Check whether a registered normalized dataset is usable evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from quant_platform.core.config import get_settings
from quant_platform.core.redact import redact_secret_text
from quant_platform.research.normalization import evaluate_normalized_dataset_usability
from quant_platform.storage.database import create_db_engine, create_session_factory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate whether a registered normalized dataset is usable "
            "research evidence. Does not compute returns or PnL."
        )
    )
    parser.add_argument("--normalized-dataset-id", required=True)
    parser.add_argument(
        "--base-dir",
        required=True,
        type=Path,
        help="Artifact folder, or a parent directory of that folder.",
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
        report = evaluate_normalized_dataset_usability(
            session, args.normalized_dataset_id, args.base_dir
        )
    except Exception as exc:
        print(f"error: {redact_secret_text(str(exc))}", file=sys.stderr)
        return 1
    finally:
        session.close()
        engine.dispose()

    blob = json.dumps(report.as_mapping(), indent=2, sort_keys=True, ensure_ascii=True)
    if "DATABASE_URL" in blob or "postgresql+psycopg://" in blob:
        print("error: catalog usability leaked a database URL", file=sys.stderr)
        return 1
    if args.as_json:
        print(blob)
        return 0 if report.usable else 1

    print(f"mode={settings.app_mode.value}")
    print(f"usable={str(report.usable).lower()}")
    print(f"normalized_dataset_id={report.normalized_dataset_id}")
    print(f"dataset_hash={report.dataset_hash or ''}")
    print(f"error_count={report.error_count}")
    print(f"warning_count={report.warning_count}")
    print(f"run_root={report.run_root or ''}")
    for issue in report.issues:
        print(f"{issue.severity}\t{issue.code}\t{issue.message}")
    return 0 if report.usable else 1


if __name__ == "__main__":
    raise SystemExit(main())
