"""Replay a point-in-time daily-bar dataset as ordered market events."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from quant_platform.core.config import get_settings
from quant_platform.core.redact import redact_secret_text
from quant_platform.research.errors import DatasetErrorCode, DatasetValidationError
from quant_platform.research.types import (
    DailyBarsDatasetRequest,
    build_daily_bars_dataset_request,
)
from quant_platform.simulation.artifacts import (
    snapshot_id_from_snapshot_dir,
    write_replay_run_artifacts,
)
from quant_platform.simulation.audit import ReplayAuditReport, audit_replay
from quant_platform.simulation.errors import SimulationError
from quant_platform.simulation.replay import (
    DailyBarReplay,
    create_daily_bar_replay,
    replay_daily_bars_snapshot,
)
from quant_platform.simulation.run_catalog import register_replay_run
from quant_platform.simulation.run_types import ReplayRunResult
from quant_platform.storage.database import create_db_engine, create_session_factory


def _parse_utc(value: str, *, field: str) -> datetime:
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise DatasetValidationError(
            f"{field} must be timezone-aware UTC (got naive {value!r})",
            code=DatasetErrorCode.NAIVE_TIMESTAMP,
        )
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Replay a PIT daily-bar dataset as ordered market events. Not a backtester."
        )
    )
    parser.add_argument(
        "--as-of", default=None, help="UTC instant, e.g. 2024-01-10T00:00:00Z"
    )
    parser.add_argument(
        "--start", default=None, help="Inclusive observation start (UTC)."
    )
    parser.add_argument("--end", default=None, help="Inclusive observation end (UTC).")
    parser.add_argument("--symbol", action="append", dest="symbols", default=None)
    parser.add_argument(
        "--exchange", action="append", dest="exchange_codes", default=None
    )
    parser.add_argument(
        "--asset-class", action="append", dest="asset_classes", default=None
    )
    parser.add_argument("--currency", default=None)
    parser.add_argument("--calendar", default=None, dest="calendar_code")
    parser.add_argument(
        "--require-open-session",
        action="store_true",
        help="Require --calendar and keep only open/half sessions.",
    )
    parser.add_argument(
        "--allow-unfiltered",
        action="store_true",
        help="Allow a query with no symbol/exchange/asset-class/currency filter.",
    )
    parser.add_argument(
        "--snapshot-dir",
        type=Path,
        default=None,
        help="Replay a local snapshot folder instead of querying PostgreSQL.",
    )
    parser.add_argument(
        "--include-sessions",
        action="store_true",
        help="Emit local calendar session events when --calendar is set (DB only).",
    )
    parser.add_argument(
        "--include-corporate-actions",
        action="store_true",
        help="Emit visible corporate actions without adjusting OHLCV (DB only).",
    )
    parser.add_argument(
        "--audit",
        action="store_true",
        help="Print stream hash, counts by kind, and audit issues.",
    )
    parser.add_argument(
        "--deterministic-id",
        action="store_true",
        help="Derive replay_id from stream hash and request hash.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Write events.jsonl, audit.json, summary.json, and manifest.json.",
    )
    parser.add_argument(
        "--register",
        action="store_true",
        help="Store replay-run metadata in PostgreSQL. Requires --output-dir.",
    )
    parser.add_argument("--notes", default=None, help="Optional replay-run note.")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.is_research_mode:
        print("error: APP_MODE must be research", file=sys.stderr)
        return 1
    if args.register and args.output_dir is None:
        print("error: --register requires --output-dir", file=sys.stderr)
        return 1

    request: DailyBarsDatasetRequest | None = None
    catalog_action: str | None = None
    run_result: ReplayRunResult | None = None
    result: DailyBarReplay | None = None
    audit_report: ReplayAuditReport | None = None
    engine = None
    session = None
    try:
        if args.snapshot_dir is not None:
            result = replay_daily_bars_snapshot(
                args.snapshot_dir,
                include_corporate_actions=args.include_corporate_actions,
                include_sessions=args.include_sessions,
                deterministic_id=args.deterministic_id,
            )
            calendar_code = None
            snapshot_id = snapshot_id_from_snapshot_dir(args.snapshot_dir)
        else:
            as_of_raw = args.as_of
            start_raw = args.start
            end_raw = args.end
            if as_of_raw is None or start_raw is None or end_raw is None:
                print(
                    "error: --as-of, --start, and --end are required "
                    "unless --snapshot-dir",
                    file=sys.stderr,
                )
                return 1
            request = build_daily_bars_dataset_request(
                as_of=_parse_utc(as_of_raw, field="as_of"),
                start_time=_parse_utc(start_raw, field="start_time"),
                end_time=_parse_utc(end_raw, field="end_time"),
                symbols=args.symbols,
                exchange_codes=args.exchange_codes,
                asset_classes=args.asset_classes,
                currency=args.currency,
                calendar_code=args.calendar_code,
                require_open_session=args.require_open_session,
                allow_unfiltered=args.allow_unfiltered,
            )
            calendar_code = request.calendar_code
            snapshot_id = None
            engine = create_db_engine(settings, connect_timeout_seconds=5)
            factory = create_session_factory(engine)
            session = factory()
            result = create_daily_bar_replay(
                session,
                request,
                include_corporate_actions=args.include_corporate_actions,
                include_sessions=args.include_sessions,
                deterministic_id=args.deterministic_id,
            )

        need_audit = args.audit or args.output_dir is not None
        if need_audit:
            audit_report = audit_replay(
                result.events,
                as_of=result.summary.as_of,
                sessions_requested=args.include_sessions,
                calendar_code=calendar_code,
            )
        if args.output_dir is not None:
            if audit_report is None:
                audit_report = audit_replay(
                    result.events,
                    as_of=result.summary.as_of,
                    sessions_requested=args.include_sessions,
                    calendar_code=calendar_code,
                )
            run_result = write_replay_run_artifacts(
                result,
                audit_report,
                args.output_dir,
                request=request,
                notes=args.notes,
                dataset_snapshot_id=snapshot_id,
                include_sessions=args.include_sessions,
                include_corporate_actions=args.include_corporate_actions,
            )
        if args.register:
            if run_result is None:
                print("error: --register requires --output-dir", file=sys.stderr)
                return 1
            if session is None:
                engine = create_db_engine(settings, connect_timeout_seconds=5)
                factory = create_session_factory(engine)
                session = factory()
            registration = register_replay_run(
                session, run_result.manifest, base_path=args.output_dir
            )
            session.commit()
            catalog_action = registration.action
    except (DatasetValidationError, SimulationError) as exc:
        if session is not None:
            session.rollback()
        print(f"error: {exc} ({exc.code})", file=sys.stderr)
        return 1
    except Exception as exc:
        if session is not None:
            session.rollback()
        print(f"error: {redact_secret_text(str(exc))}", file=sys.stderr)
        return 1
    finally:
        if session is not None:
            session.close()
        if engine is not None:
            engine.dispose()

    if result is None:
        print("error: replay produced no result", file=sys.stderr)
        return 1

    if args.as_json:
        payload = result.summary.as_mapping()
        if audit_report is not None:
            payload["audit"] = audit_report.as_mapping()
        if run_result is not None:
            payload["run"] = {
                "stream_hash": run_result.manifest.stream_hash,
                "manifest_hash": run_result.manifest.manifest_hash,
                "boundary_ok": run_result.manifest.boundary_ok,
                "pre_known_event_count": run_result.manifest.pre_known_event_count,
                "artifacts": [
                    item.as_mapping() for item in run_result.manifest.artifacts
                ],
                "catalog": catalog_action,
            }
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True))
        return 0

    _print_text(
        settings.app_mode.value, result, audit_report, run_result, catalog_action
    )
    return 0


def _print_text(
    mode: str,
    result: DailyBarReplay,
    audit_report: ReplayAuditReport | None,
    run_result: ReplayRunResult | None,
    catalog_action: str | None,
) -> None:
    summary = result.summary
    print(f"mode={mode}")
    print(f"replay_id={summary.replay_id}")
    print(f"source_type={summary.source_type}")
    print(f"event_count={summary.event_count}")
    print(f"bar_count={summary.bar_count}")
    print(f"pre_known_event_count={summary.pre_known_event_count}")
    print(f"market_event_count={summary.market_event_count}")
    print(f"session_event_count={summary.session_event_count}")
    print(f"corporate_action_event_count={summary.corporate_action_event_count}")
    print(f"instrument_count={summary.instrument_count}")
    first = (
        "" if summary.first_event_time is None else summary.first_event_time.isoformat()
    )
    last = (
        "" if summary.last_event_time is None else summary.last_event_time.isoformat()
    )
    first_market = (
        ""
        if summary.first_market_event_time is None
        else summary.first_market_event_time.isoformat()
    )
    last_market = (
        ""
        if summary.last_market_event_time is None
        else summary.last_market_event_time.isoformat()
    )
    print(f"first_event_time={first}")
    print(f"last_event_time={last}")
    print(f"first_market_event_time={first_market}")
    print(f"last_market_event_time={last_market}")
    if run_result is not None:
        print(f"stream_hash={run_result.manifest.stream_hash}")
        print(f"manifest_hash={run_result.manifest.manifest_hash}")
        print(f"boundary_ok={str(run_result.manifest.boundary_ok).lower()}")
        print("events=events.jsonl")
        print("audit=audit.json")
        print("summary=summary.json")
        print("manifest=manifest.json")
    if catalog_action is not None:
        print(f"catalog={catalog_action}")
    if audit_report is None:
        return
    if run_result is None:
        print(f"stream_hash={audit_report.stream_hash}")
        print(f"boundary_ok={str(audit_report.boundary_ok).lower()}")
    print(
        "starts_with_replay_started="
        f"{str(audit_report.starts_with_replay_started).lower()}"
    )
    print(
        "ends_with_replay_finished="
        f"{str(audit_report.ends_with_replay_finished).lower()}"
    )
    for kind in sorted(audit_report.counts_by_kind):
        print(f"event_count_{kind}={audit_report.counts_by_kind[kind]}")
    print(f"warnings={audit_report.warning_count}")
    print(f"errors={audit_report.error_count}")
    audit_first = (
        ""
        if audit_report.first_event_time is None
        else audit_report.first_event_time.isoformat()
    )
    audit_last = (
        ""
        if audit_report.last_event_time is None
        else audit_report.last_event_time.isoformat()
    )
    print(f"audit_first_event_time={audit_first}")
    print(f"audit_last_event_time={audit_last}")
    for issue in audit_report.issues:
        if issue.severity in {"warning", "error"}:
            print(f"{issue.severity}={issue.code}:{issue.message}")


if __name__ == "__main__":
    raise SystemExit(main())
