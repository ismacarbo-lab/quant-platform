"""Offline dry-run backtest foundation. Not a strategy or trading engine."""

from quant_platform.backtest.artifacts import write_backtest_artifacts
from quant_platform.backtest.catalog import (
    backtest_run_is_reproducible,
    backtest_run_is_usable,
    compare_backtest_runs,
    compare_catalog_backtest_runs,
    get_backtest_run_by_id,
    get_backtest_run_by_manifest_hash,
    list_backtest_runs,
    raise_if_manifest_hash_conflict,
    register_backtest_run,
    validate_backtest_run_manifest,
)
from quant_platform.backtest.compare import (
    BacktestRunDiff,
    diff_backtest_runs,
    diff_catalog_backtest_runs,
)
from quant_platform.backtest.engine import (
    execute_backtest,
    require_backtest_readiness,
    run_backtest_from_replay_run,
)
from quant_platform.backtest.errors import BacktestError, BacktestErrorCode
from quant_platform.backtest.integrity import (
    resolve_backtest_run_directory,
    verify_backtest_artifacts,
    verify_backtest_catalog,
    verify_registered_backtest_run,
)
from quant_platform.backtest.integrity_types import (
    BacktestArtifactStatus,
    BacktestArtifactVerificationIssue,
    BacktestArtifactVerificationReport,
    BacktestIntegrityCode,
)
from quant_platform.backtest.policy import (
    EventCountingBacktestPolicy,
    NoOpBacktestPolicy,
)
from quant_platform.backtest.readiness import (
    BacktestUsabilityReport,
    build_backtest_usability_report,
    evaluate_backtest_result_usability,
)
from quant_platform.backtest.results import (
    derive_backtest_id,
    hash_backtest_counts,
    hash_backtest_mapping,
    hash_backtest_result,
    hash_backtest_summary,
)
from quant_platform.backtest.types import (
    NOOP_POLICY_NAME,
    BacktestArtifact,
    BacktestManifest,
    BacktestRequest,
    BacktestResult,
    BacktestRunCatalogEntry,
    BacktestRunComparison,
    BacktestSummary,
    build_backtest_run_catalog_filters,
)

__all__ = [
    "NOOP_POLICY_NAME",
    "BacktestArtifact",
    "BacktestArtifactStatus",
    "BacktestArtifactVerificationIssue",
    "BacktestArtifactVerificationReport",
    "BacktestError",
    "BacktestErrorCode",
    "BacktestIntegrityCode",
    "BacktestManifest",
    "BacktestRequest",
    "BacktestResult",
    "BacktestRunCatalogEntry",
    "BacktestRunComparison",
    "BacktestRunDiff",
    "BacktestSummary",
    "BacktestUsabilityReport",
    "EventCountingBacktestPolicy",
    "NoOpBacktestPolicy",
    "backtest_run_is_reproducible",
    "backtest_run_is_usable",
    "build_backtest_run_catalog_filters",
    "build_backtest_usability_report",
    "compare_backtest_runs",
    "compare_catalog_backtest_runs",
    "derive_backtest_id",
    "diff_backtest_runs",
    "diff_catalog_backtest_runs",
    "evaluate_backtest_result_usability",
    "execute_backtest",
    "get_backtest_run_by_id",
    "get_backtest_run_by_manifest_hash",
    "hash_backtest_counts",
    "hash_backtest_mapping",
    "hash_backtest_result",
    "hash_backtest_summary",
    "list_backtest_runs",
    "raise_if_manifest_hash_conflict",
    "register_backtest_run",
    "require_backtest_readiness",
    "resolve_backtest_run_directory",
    "run_backtest_from_replay_run",
    "validate_backtest_run_manifest",
    "verify_backtest_artifacts",
    "verify_backtest_catalog",
    "verify_registered_backtest_run",
    "write_backtest_artifacts",
]
