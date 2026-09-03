"""Run one offline data-contract conformance report. Not a vendor client."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from quant_platform.core.config import get_settings
from quant_platform.core.redact import redact_secret_text
from quant_platform.data.contracts.conformance import (
    build_data_contract_conformance_report,
    build_data_contract_conformance_request,
)
from quant_platform.data.contracts.conformance_artifacts import (
    write_data_contract_conformance_artifacts,
)
from quant_platform.data.contracts.conformance_types import (
    DataContractConformanceRequest,
)
from quant_platform.data.contracts.errors import VendorContractError
from quant_platform.data.contracts.fake_provider import (
    FakeVendorPayloadProvider,
    load_offline_vendor_payload_batch,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate an offline vendor-agnostic payload batch against the "
            "data source contract. Does not download data, call vendors, "
            "or compute returns."
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
        help="Write conformance report and manifest JSON.",
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
        request = _request_from_fixture_dir(args.fixture_dir)
        report = build_data_contract_conformance_report(batch, request)
        if args.output_dir is not None:
            write_data_contract_conformance_artifacts(
                report,
                args.output_dir,
                batch=batch,
                include_source_payload=False,
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
        print("error: conformance report leaked a database URL", file=sys.stderr)
        return 1
    if args.json:
        print(blob)
    else:
        summary = report.summary
        print(
            f"data contract conformance: ok={str(report.ok).lower()} "
            f"issues={summary.issue_counts.total} "
            f"hash={report.conformance_hash}"
        )
    return 0 if report.ok else 1


def _request_from_fixture_dir(
    fixture_dir: Path | None,
) -> DataContractConformanceRequest:
    if fixture_dir is None:
        return build_data_contract_conformance_request()
    path = fixture_dir / "request.json"
    if not path.is_file():
        return build_data_contract_conformance_request()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise VendorContractError("request.json must be a JSON object")
    return build_data_contract_conformance_request(
        contract_name=str(
            payload.get("contract_name") or "vendor_agnostic_data_source"
        ),
        contract_version=str(payload.get("contract_version") or "1"),
        source_name=(
            None
            if payload.get("source_name") is None
            else str(payload.get("source_name"))
        ),
        created_by=str(payload.get("created_by") or "offline_conformance_runner"),
        notes=None if payload.get("notes") is None else str(payload.get("notes")),
        include_source_payload=bool(payload.get("include_source_payload", False)),
    )


if __name__ == "__main__":
    sys.exit(main())
