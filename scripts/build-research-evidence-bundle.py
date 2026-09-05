"""Build a local research evidence bundle. Not trading and not a vendor client."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from quant_platform.backtest.errors import BacktestError
from quant_platform.backtest.policy_registry import registered_policy_names
from quant_platform.core.config import get_settings
from quant_platform.core.redact import redact_secret_text
from quant_platform.release.evidence_bundle import build_research_evidence_bundle
from quant_platform.release.evidence_types import (
    DEFAULT_POLICY_NAME,
    EvidenceBundleError,
    ResearchEvidenceBundleRequest,
)
from quant_platform.storage.database import create_db_engine, create_session_factory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build a local research evidence bundle from fixtures. "
            "Does not trade, download data, or call vendors."
        )
    )
    parser.add_argument(
        "--fixture-dir",
        type=Path,
        required=True,
        help="Directory of local CSV fixtures.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory for the evidence bundle artifacts.",
    )
    parser.add_argument(
        "--policy-name",
        default=DEFAULT_POLICY_NAME,
        help=(
            "Registered research policy ("
            + ", ".join(sorted(registered_policy_names()))
            + "). Default: data_quality. Not a strategy."
        ),
    )
    parser.add_argument(
        "--policy-config-json",
        default=None,
        help="JSON object of policy config. Not a strategy payload.",
    )
    parser.add_argument(
        "--deterministic-id",
        action="store_true",
        help="Derive replay, backtest, experiment, and bundle ids from hashes.",
    )
    parser.add_argument(
        "--include-normalized-dataset",
        action="store_true",
        help=(
            "Build a derived normalized dataset into normalized_dataset/. "
            "Opt-in; default bundles stay unchanged. No returns or PnL."
        ),
    )
    parser.add_argument(
        "--normalization-adjustment-mode",
        default="split_only",
        help="Adjustment mode when --include-normalized-dataset is set.",
    )
    parser.add_argument(
        "--register-normalized-dataset",
        action="store_true",
        help=(
            "Register normalized-dataset catalog metadata when "
            "--include-normalized-dataset is also set. Metadata only."
        ),
    )
    parser.add_argument(
        "--allow-existing-fixture-data",
        action="store_true",
        help=(
            "If ingest inserts 0 bars, verify existing rows match the "
            "fixtures and reuse them. Default is strict (fail). Does not "
            "delete, truncate, or rewrite daily_bars."
        ),
    )
    parser.add_argument(
        "--include-contract-payload-intake",
        action="store_true",
        help=(
            "Attach an offline contract-payload intake plan and artifacts. "
            "Opt-in; default bundles stay unchanged. Dry-run unless "
            "--contract-intake-write-db is also set. No vendor HTTP."
        ),
    )
    parser.add_argument(
        "--contract-intake-write-db",
        action="store_true",
        help=(
            "Execute intake through existing PIT ingest. Requires "
            "--include-contract-payload-intake. Does not rewrite daily_bars."
        ),
    )
    parser.add_argument(
        "--contract-intake-batch-file",
        type=Path,
        default=None,
        help="Local VendorPayloadBatch JSON. Mutually exclusive with fixture-dir.",
    )
    parser.add_argument(
        "--contract-intake-fixture-dir",
        type=Path,
        default=None,
        help="Local intake fixture directory containing batch.json.",
    )
    parser.add_argument(
        "--contract-intake-output-dir-name",
        default="contract_payload_intake",
        help="Relative subdirectory for intake artifacts inside the bundle.",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.is_research_mode:
        print("error: APP_MODE must be research", file=sys.stderr)
        return 1

    policy_config: dict[str, object] | None = None
    if args.policy_config_json is not None:
        try:
            loaded = json.loads(args.policy_config_json)
        except json.JSONDecodeError as exc:
            print(
                f"error: policy-config-json is not valid JSON ({exc})",
                file=sys.stderr,
            )
            return 1
        if not isinstance(loaded, dict):
            print("error: policy-config-json must be a JSON object", file=sys.stderr)
            return 1
        policy_config = loaded

    if args.contract_intake_write_db and not args.include_contract_payload_intake:
        print(
            "error: --contract-intake-write-db requires "
            "--include-contract-payload-intake",
            file=sys.stderr,
        )
        return 1
    if (
        args.contract_intake_batch_file is not None
        and args.contract_intake_fixture_dir is not None
    ):
        print(
            "error: specify only one of --contract-intake-batch-file or "
            "--contract-intake-fixture-dir",
            file=sys.stderr,
        )
        return 1

    engine = create_db_engine(settings, connect_timeout_seconds=5)
    factory = create_session_factory(engine)
    session = factory()
    try:
        request = ResearchEvidenceBundleRequest(
            fixture_dir=args.fixture_dir,
            output_dir=args.output_dir,
            policy_name=args.policy_name,
            policy_config=policy_config,
            deterministic_id=bool(args.deterministic_id),
            resolve_git=not bool(args.deterministic_id),
            include_normalized_dataset=bool(args.include_normalized_dataset),
            register_normalized_dataset=bool(args.register_normalized_dataset),
            normalization_adjustment_mode=args.normalization_adjustment_mode,
            allow_existing_fixture_data=bool(args.allow_existing_fixture_data),
            include_contract_payload_intake=bool(args.include_contract_payload_intake),
            contract_intake_write_db=bool(args.contract_intake_write_db),
            contract_intake_batch_file=args.contract_intake_batch_file,
            contract_intake_fixture_dir=args.contract_intake_fixture_dir,
            contract_intake_output_dir_name=args.contract_intake_output_dir_name,
        )
        result = build_research_evidence_bundle(session, request)
        if result.ok:
            session.commit()
        else:
            session.rollback()
    except (EvidenceBundleError, BacktestError, OSError, ValueError) as exc:
        session.rollback()
        print(f"error: {redact_secret_text(str(exc))}", file=sys.stderr)
        return 1
    finally:
        session.close()
        engine.dispose()

    payload = result.summary_mapping()
    blob = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True)
    if "DATABASE_URL" in blob or "postgresql+psycopg://" in blob:
        print("error: evidence bundle leaked a database URL", file=sys.stderr)
        return 1
    if args.as_json:
        print(blob)
    else:
        print(f"research evidence bundle: ok={str(result.ok).lower()}")
        print(f"bundle_id={result.manifest.bundle_id}")
        print(f"bundle_hash={result.bundle_hash}")
        print(f"dataset_snapshot_id={result.manifest.dataset_snapshot_id or ''}")
        print(f"replay_id={result.manifest.replay_id or ''}")
        print(f"backtest_id={result.manifest.backtest_id or ''}")
        print(f"experiment_id={result.manifest.experiment_id or ''}")
        print(f"fixture_data_mode={result.manifest.fixture_data_mode or ''}")
        reuse = result.manifest.fixture_reuse
        if reuse is not None:
            print(f"inserted_bar_count={reuse.inserted_bar_count}")
            print(f"reused_bar_count={reuse.reused_bar_count}")
        if result.manifest.contract_intake_included:
            print("contract_intake_included=true")
            print(
                "contract_intake_write_db="
                + str(bool(result.manifest.contract_intake_write_db)).lower()
            )
            status = result.manifest.contract_intake_status or ""
            print(f"contract_intake_status={status}")
            digest = result.manifest.contract_intake_hash or ""
            print(f"contract_intake_hash={digest}")
            inserted = result.manifest.contract_intake_inserted_counts or {}
            skipped = result.manifest.contract_intake_skipped_counts or {}
            print(f"contract_intake_inserted_total={inserted.get('total', 0)}")
            print(f"contract_intake_skipped_total={skipped.get('total', 0)}")
        print(f"errors={len(result.manifest.errors)}")
        for issue in result.manifest.errors:
            print(f"error\t{issue.code}\t{issue.message}")
        for issue in result.manifest.warnings:
            print(f"warning\t{issue.code}\t{issue.message}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
