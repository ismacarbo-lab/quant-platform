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
from quant_platform.backtest.engine import (
    execute_backtest,
    require_backtest_readiness,
    run_backtest_from_replay_run,
)
from quant_platform.backtest.errors import BacktestError, BacktestErrorCode
from quant_platform.backtest.policy import (
    EventCountingBacktestPolicy,
    NoOpBacktestPolicy,
)
from quant_platform.backtest.results import (
    derive_backtest_id,
    hash_backtest_counts,
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
    "BacktestError",
    "BacktestErrorCode",
    "BacktestManifest",
    "BacktestRequest",
    "BacktestResult",
    "BacktestRunCatalogEntry",
    "BacktestRunComparison",
    "BacktestSummary",
    "EventCountingBacktestPolicy",
    "NoOpBacktestPolicy",
    "backtest_run_is_reproducible",
    "backtest_run_is_usable",
    "build_backtest_run_catalog_filters",
    "compare_backtest_runs",
    "compare_catalog_backtest_runs",
    "derive_backtest_id",
    "execute_backtest",
    "get_backtest_run_by_id",
    "get_backtest_run_by_manifest_hash",
    "hash_backtest_counts",
    "hash_backtest_result",
    "hash_backtest_summary",
    "list_backtest_runs",
    "raise_if_manifest_hash_conflict",
    "register_backtest_run",
    "require_backtest_readiness",
    "run_backtest_from_replay_run",
    "validate_backtest_run_manifest",
    "write_backtest_artifacts",
]
