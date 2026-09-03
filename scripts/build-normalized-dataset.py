"""Build a local normalized daily-bar research view. Not trading."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from uuid import UUID

from quant_platform.core.config import get_settings
from quant_platform.core.redact import redact_secret_text
from quant_platform.research.normalization import (
    NormalizationError,
    build_normalization_request,
    build_normalized_daily_bars_dataset,
    build_normalized_dataset_registration,
    register_normalized_dataset,
    write_normalized_dataset_artifacts,
)
from quant_platform.research.normalization.types import DEFAULT_ADJUSTMENT_MODE
from quant_platform.storage.database import create_db_engine, create_session_factory


def _parse_utc(value: str, *, field: str) -> datetime:
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise NormalizationError(f"{field} must be timezone-aware UTC")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build a derived corporate-action-normalized daily-bar dataset. "
            "Does not mutate silver bars, trade, or call vendors."
        )
    )
    parser.add_argument("--source-name", required=True)
    parser.add_argument("--symbol", action="append", dest="symbols", default=None)
    parser.add_argument(
        "--instrument-id",
        action="append",
        dest="instrument_ids",
        default=None,
    )
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--calendar-code", default=None)
    parser.add_argument(
        "--adjustment-mode",
        default=DEFAULT_ADJUSTMENT_MODE.value,
        help="none | split_only | split_and_reverse_split | informational",
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--register",
        action="store_true",
        help="Store catalog metadata in PostgreSQL. Does not store OHLCV rows.",
    )
    parser.add_argument("--notes", default=None)
    parser.add_argument("--normalized-dataset-id", default=None)
    parser.add_argument(
        "--deterministic-id",
        action="store_true",
        help="Derive normalized_dataset_id from dataset_hash, mode, and as_of.",
    )
    parser.add_argument("--source-snapshot-id", default=None)
    parser.add_argument("--source-replay-id", default=None)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.is_research_mode:
        print("error: APP_MODE must be research", file=sys.stderr)
        return 1

    instrument_ids: list[UUID] | None = None
    if args.instrument_ids:
        try:
            instrument_ids = [UUID(item) for item in args.instrument_ids]
        except ValueError as exc:
            print(f"error: instrument-id is not a UUID ({exc})", file=sys.stderr)
            return 1

    try:
        request = build_normalization_request(
            as_of=_parse_utc(args.as_of, field="as_of"),
            start_time=_parse_utc(args.start, field="start_time"),
            end_time=_parse_utc(args.end, field="end_time"),
            source_name=args.source_name,
            adjustment_mode=args.adjustment_mode,
            symbols=args.symbols,
            instrument_ids=instrument_ids,
            calendar_code=args.calendar_code,
        )
    except NormalizationError as exc:
        print(f"error: {exc} ({exc.code})", file=sys.stderr)
        return 1

    engine = create_db_engine(settings, connect_timeout_seconds=5)
    factory = create_session_factory(engine)
    session = factory()
    catalog_id: str | None = None
    catalog_action: str | None = None
    try:
        dataset = build_normalized_daily_bars_dataset(session, request)
        manifest = write_normalized_dataset_artifacts(dataset, args.output_dir)
        if args.register:
            entry = build_normalized_dataset_registration(
                dataset,
                manifest,
                normalized_dataset_id=args.normalized_dataset_id,
                deterministic_id=bool(args.deterministic_id),
                source_snapshot_id=args.source_snapshot_id,
                source_replay_id=args.source_replay_id,
                notes=args.notes,
            )
            registration = register_normalized_dataset(session, entry)
            session.commit()
            catalog_id = registration.entry.normalized_dataset_id
            catalog_action = registration.action
    except NormalizationError as exc:
        session.rollback()
        print(f"error: {exc} ({exc.code})", file=sys.stderr)
        return 1
    except Exception as exc:
        session.rollback()
        print(f"error: {redact_secret_text(str(exc))}", file=sys.stderr)
        return 1
    finally:
        session.close()
        engine.dispose()

    payload = {
        "ok": dataset.report.ok,
        "dataset_hash": dataset.dataset_hash,
        "raw_dataset_hash": dataset.raw_dataset_hash,
        "bar_count": dataset.report.bar_count,
        "applied_action_count": dataset.report.applied_action_count,
        "issue_count": dataset.report.issue_count,
        "adjustment_mode": dataset.request.adjustment_mode.value,
        "output_dir": str(args.output_dir),
        "manifest_kind": manifest.kind,
    }
    if catalog_id is not None:
        payload["normalized_dataset_id"] = catalog_id
        payload["catalog"] = catalog_action
    blob = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True)
    if "DATABASE_URL" in blob or "postgresql+psycopg://" in blob:
        print("error: normalization output leaked a database URL", file=sys.stderr)
        return 1
    if args.as_json:
        print(blob)
        return 0 if dataset.report.ok else 1
    print(f"mode={settings.app_mode.value}")
    print(f"ok={str(dataset.report.ok).lower()}")
    print(f"dataset_hash={dataset.dataset_hash}")
    print(f"bar_count={dataset.report.bar_count}")
    print(f"applied_action_count={dataset.report.applied_action_count}")
    print(f"issue_count={dataset.report.issue_count}")
    print(f"output_dir={args.output_dir}")
    if catalog_id is not None:
        print(f"normalized_dataset_id={catalog_id}")
        print(f"catalog={catalog_action}")
    return 0 if dataset.report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
