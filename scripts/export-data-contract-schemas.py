"""Export vendor-agnostic data-contract schemas. Offline; no vendors."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from quant_platform.core.config import get_settings
from quant_platform.core.redact import redact_secret_text
from quant_platform.data.contracts.errors import VendorContractError
from quant_platform.data.contracts.schema_export import (
    build_contract_schema_bundle,
    write_contract_schema_bundle,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Export deterministic JSON schemas for vendor-agnostic data "
            "contracts. Does not download data, call vendors, or compute "
            "returns."
        )
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Write data_contract_schema_bundle.json and the manifest.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the schema bundle as JSON.",
    )
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
        bundle = build_contract_schema_bundle()
        if args.output_dir is not None:
            write_contract_schema_bundle(args.output_dir, bundle=bundle)
    except VendorContractError as exc:
        print(redact_secret_text(str(exc)), file=sys.stderr)
        return 1
    except OSError as exc:
        print(redact_secret_text(str(exc)), file=sys.stderr)
        return 1
    blob = json.dumps(
        bundle.as_mapping(),
        indent=2,
        sort_keys=True,
        ensure_ascii=True,
    )
    if "DATABASE_URL" in blob or "postgresql+psycopg://" in blob:
        print("error: schema bundle leaked a database URL", file=sys.stderr)
        return 1
    if args.json:
        print(blob)
    else:
        print(
            f"data contract schema export: schemas={bundle.schema_count} "
            f"hash={bundle.bundle_hash}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
