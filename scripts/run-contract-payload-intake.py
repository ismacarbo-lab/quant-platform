"""Run one offline contract-payload intake. Not a vendor client."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from quant_platform.core.config import get_settings
from quant_platform.core.redact import redact_secret_text
from quant_platform.data.contracts.errors import VendorContractError
from quant_platform.data.contracts.fake_provider import (
    FakeVendorPayloadProvider,
    load_offline_vendor_payload_batch,
)
from quant_platform.data.contracts.intake import (
    build_contract_payload_intake_plan,
    build_contract_payload_intake_report,
    build_contract_payload_intake_request,
    execute_contract_payload_intake,
    relabel_contract_payload_batch,
)
from quant_platform.data.contracts.intake_artifacts import (
    write_contract_payload_intake_artifacts,
)
from quant_platform.data.contracts.intake_types import ContractPayloadIntakeRequest
from quant_platform.storage.database import create_db_engine, create_session_factory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Map an offline vendor-agnostic payload batch onto the research "
            "ingestion layer. Dry-run by default. Does not download data, "
            "call vendors, or compute returns."
        )
    )
    parser.add_argument(
        "--batch-file",
        type=Path,
        default=None,
        help="Local JSON batch file.",
    )
    parser.add_argument(
        "--fixture-dir",
        type=Path,
        default=None,
        help="Directory containing batch.json.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Write intake plan, report, and manifest JSON.",
    )
    parser.add_argument(
        "--write-db",
        action="store_true",
        help="Write accepted rows to PostgreSQL. Off by default.",
    )
    parser.add_argument(
        "--allow-invalid",
        action="store_true",
        help="Build a plan for invalid batches. Still does not write DB.",
    )
    parser.add_argument(
        "--source-name",
        default=None,
        help="Override batch source_name when the fixture omits one.",
    )
    parser.add_argument("--json", action="store_true", help="Print the report as JSON.")
    args = parser.parse_args(argv)
    try:
        settings = get_settings()
    except Exception as exc:
        print(redact_secret_text(str(exc)), file=sys.stderr)
        return 1
    if not settings.is_research_mode:
        print("APP_MODE must be research", file=sys.stderr)
        return 1
    try:
        if args.batch_file is not None:
            batch = load_offline_vendor_payload_batch(args.batch_file)
        elif args.fixture_dir is not None:
            batch = load_offline_vendor_payload_batch(args.fixture_dir)
        else:
            batch = FakeVendorPayloadProvider(validate=False).load_batch()
        if args.source_name:
            batch = relabel_contract_payload_batch(batch, str(args.source_name))
        request = _request_from_args(args)
        plan = build_contract_payload_intake_plan(batch, request)
        report = build_contract_payload_intake_report(plan)
        if args.write_db:
            engine = create_db_engine(settings, connect_timeout_seconds=5)
            factory = create_session_factory(engine)
            session = factory()
            try:
                report = execute_contract_payload_intake(session, batch, request)
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()
                engine.dispose()
        if args.output_dir is not None:
            write_contract_payload_intake_artifacts(
                plan,
                report,
                args.output_dir,
                batch=batch,
                include_source_payload=request.include_source_payload,
            )
    except VendorContractError as exc:
        print(redact_secret_text(str(exc)), file=sys.stderr)
        return 1
    except OSError as exc:
        print(redact_secret_text(str(exc)), file=sys.stderr)
        return 1
    blob = json.dumps(
        report.as_mapping(),
        indent=2,
        sort_keys=True,
        ensure_ascii=True,
    )
    if "DATABASE_URL" in blob or "postgresql+psycopg://" in blob:
        print("error: intake report leaked a database URL", file=sys.stderr)
        return 1
    if args.json:
        print(blob)
    else:
        mode = "write_db" if report.db_executed else "dry_run"
        print(
            f"contract payload intake: ok={str(report.ok).lower()} "
            f"mode={mode} issues={len(report.issues)} "
            f"hash={report.intake_hash}"
        )
    if args.write_db and not report.db_executed:
        return 1
    return 0 if report.ok else 1


def _request_from_args(args: argparse.Namespace) -> ContractPayloadIntakeRequest:
    payload: dict[str, object] = {}
    if args.fixture_dir is not None:
        path = Path(args.fixture_dir) / "request.json"
        if path.is_file():
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                raise VendorContractError("request.json must be a JSON object")
            payload = loaded
    allow_invalid = bool(args.allow_invalid) or bool(
        payload.get("allow_invalid", False)
    )
    return build_contract_payload_intake_request(
        contract_name=str(
            payload.get("contract_name") or "vendor_agnostic_data_source"
        ),
        contract_version=str(payload.get("contract_version") or "1"),
        source_name=(
            None
            if args.source_name is None and payload.get("source_name") is None
            else str(args.source_name or payload.get("source_name"))
        ),
        created_by=str(payload.get("created_by") or "offline_intake_runner"),
        notes=None if payload.get("notes") is None else str(payload.get("notes")),
        write_db=bool(args.write_db),
        allow_invalid=allow_invalid,
        include_source_payload=bool(payload.get("include_source_payload", False)),
    )


if __name__ == "__main__":
    sys.exit(main())
