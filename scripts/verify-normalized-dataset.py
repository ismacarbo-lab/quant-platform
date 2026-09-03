"""Verify local normalization artifacts or a catalog row. Read-only."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from quant_platform.core.config import get_settings
from quant_platform.core.redact import redact_secret_text
from quant_platform.research.normalization import (
    evaluate_normalized_dataset_usability,
    verify_normalization_artifacts,
)
from quant_platform.storage.database import create_db_engine, create_session_factory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify local corporate-action normalization artifacts, "
            "or a registered catalog row. Does not trade or call vendors."
        )
    )
    parser.add_argument("--run-dir", type=Path, default=None)
    parser.add_argument("--normalized-dataset-id", default=None)
    parser.add_argument("--base-dir", type=Path, default=None)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.is_research_mode:
        print("error: APP_MODE must be research", file=sys.stderr)
        return 1

    catalog_id = (args.normalized_dataset_id or "").strip() or None
    if args.run_dir is None and catalog_id is None:
        print(
            "error: provide --run-dir and/or --normalized-dataset-id",
            file=sys.stderr,
        )
        return 1

    if catalog_id is None:
        try:
            report = verify_normalization_artifacts(args.run_dir)
        except Exception as exc:
            print(f"error: {redact_secret_text(str(exc))}", file=sys.stderr)
            return 1
        payload = report.as_mapping()
        ok = report.ok
    else:
        base_dir = args.base_dir if args.base_dir is not None else args.run_dir
        engine = create_db_engine(settings, connect_timeout_seconds=5)
        factory = create_session_factory(engine)
        session = factory()
        try:
            usability = evaluate_normalized_dataset_usability(
                session, catalog_id, base_dir
            )
        except Exception as exc:
            print(f"error: {redact_secret_text(str(exc))}", file=sys.stderr)
            return 1
        finally:
            session.close()
            engine.dispose()
        payload = usability.as_mapping()
        ok = usability.usable

    blob = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True)
    if "DATABASE_URL" in blob or "postgresql+psycopg://" in blob:
        print("error: normalization integrity leaked a database URL", file=sys.stderr)
        return 1
    if args.as_json:
        print(blob)
    else:
        print(f"mode={settings.app_mode.value}")
        print(f"ok={str(ok).lower()}")
        print(f"dataset_hash={payload.get('dataset_hash') or ''}")
        print(f"errors={payload.get('error_count')}")
        print(f"warnings={payload.get('warning_count')}")
        issues = payload.get("issues")
        if isinstance(issues, list):
            for issue in issues:
                if not isinstance(issue, dict):
                    continue
                print(
                    f"{issue.get('severity')}\t{issue.get('code')}\t"
                    f"{issue.get('message')}"
                )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
