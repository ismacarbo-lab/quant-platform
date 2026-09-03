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
        print(f"errors={len(result.manifest.errors)}")
        for issue in result.manifest.errors:
            print(f"error\t{issue.code}\t{issue.message}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
