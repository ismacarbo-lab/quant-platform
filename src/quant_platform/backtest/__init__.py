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
from quant_platform.backtest.experiment_artifacts import (
    write_backtest_experiment_artifacts,
)
from quant_platform.backtest.experiment_catalog import (
    compare_backtest_experiments,
    compare_catalog_backtest_experiments,
    get_backtest_experiment_by_id,
    get_backtest_experiment_by_manifest_hash,
    list_backtest_experiments,
    register_backtest_experiment,
    validate_backtest_experiment_manifest,
)
from quant_platform.backtest.experiment_integrity import (
    resolve_experiment_directory,
    verify_backtest_experiment_artifacts,
)
from quant_platform.backtest.experiment_readiness import (
    evaluate_backtest_experiment_usability,
)
from quant_platform.backtest.experiment_readiness_types import (
    BacktestExperimentResearchReport,
    BacktestExperimentUsabilityReport,
)
from quant_platform.backtest.experiment_report_artifacts import (
    write_backtest_experiment_report_artifacts,
)
from quant_platform.backtest.experiment_reports import (
    build_backtest_experiment_research_report,
    hash_backtest_experiment_report,
)
from quant_platform.backtest.experiment_types import (
    BacktestExperimentComparison,
    BacktestExperimentManifest,
    BacktestExperimentMember,
    BacktestExperimentRequest,
    BacktestExperimentResult,
    BacktestExperimentSummary,
    build_backtest_experiment_catalog_filters,
)
from quant_platform.backtest.experiments import (
    build_experiment_result,
    hash_backtest_experiment,
    run_backtest_experiment,
)
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
from quant_platform.backtest.observation_reports import (
    ObservationReport,
    build_observation_report,
)
from quant_platform.backtest.observations import (
    PolicyRunOutput,
    ResearchObservation,
    hash_policy_output,
)
from quant_platform.backtest.policy import (
    EventCountingBacktestPolicy,
    EventCountingResearchPolicy,
    NoOpBacktestPolicy,
)
from quant_platform.backtest.policy_interface import ResearchPolicy
from quant_platform.backtest.policy_output_integrity import (
    compare_policy_outputs,
    verify_policy_output,
)
from quant_platform.backtest.policy_output_types import (
    PolicyOutputComparison,
    PolicyOutputVerificationReport,
)
from quant_platform.backtest.policy_registry import (
    get_research_policy,
    registered_policy_names,
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
    EVENT_COUNTING_POLICY_NAME,
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
    "EVENT_COUNTING_POLICY_NAME",
    "NOOP_POLICY_NAME",
    "BacktestArtifact",
    "BacktestArtifactStatus",
    "BacktestArtifactVerificationIssue",
    "BacktestArtifactVerificationReport",
    "BacktestError",
    "BacktestErrorCode",
    "BacktestExperimentComparison",
    "BacktestExperimentManifest",
    "BacktestExperimentMember",
    "BacktestExperimentRequest",
    "BacktestExperimentResearchReport",
    "BacktestExperimentResult",
    "BacktestExperimentSummary",
    "BacktestExperimentUsabilityReport",
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
    "EventCountingResearchPolicy",
    "NoOpBacktestPolicy",
    "ObservationReport",
    "PolicyOutputComparison",
    "PolicyOutputVerificationReport",
    "PolicyRunOutput",
    "ResearchObservation",
    "ResearchPolicy",
    "backtest_run_is_reproducible",
    "backtest_run_is_usable",
    "build_backtest_experiment_catalog_filters",
    "build_backtest_experiment_research_report",
    "build_backtest_run_catalog_filters",
    "build_backtest_usability_report",
    "build_experiment_result",
    "build_observation_report",
    "compare_backtest_experiments",
    "compare_backtest_runs",
    "compare_catalog_backtest_experiments",
    "compare_catalog_backtest_runs",
    "compare_policy_outputs",
    "derive_backtest_id",
    "diff_backtest_runs",
    "diff_catalog_backtest_runs",
    "evaluate_backtest_experiment_usability",
    "evaluate_backtest_result_usability",
    "execute_backtest",
    "get_backtest_experiment_by_id",
    "get_backtest_experiment_by_manifest_hash",
    "get_backtest_run_by_id",
    "get_backtest_run_by_manifest_hash",
    "get_research_policy",
    "hash_backtest_counts",
    "hash_backtest_experiment",
    "hash_backtest_experiment_report",
    "hash_backtest_mapping",
    "hash_backtest_result",
    "hash_backtest_summary",
    "hash_policy_output",
    "list_backtest_experiments",
    "list_backtest_runs",
    "raise_if_manifest_hash_conflict",
    "register_backtest_experiment",
    "register_backtest_run",
    "registered_policy_names",
    "require_backtest_readiness",
    "resolve_backtest_run_directory",
    "resolve_experiment_directory",
    "run_backtest_experiment",
    "run_backtest_from_replay_run",
    "validate_backtest_experiment_manifest",
    "validate_backtest_run_manifest",
    "verify_backtest_artifacts",
    "verify_backtest_catalog",
    "verify_backtest_experiment_artifacts",
    "verify_policy_output",
    "verify_registered_backtest_run",
    "write_backtest_artifacts",
    "write_backtest_experiment_artifacts",
    "write_backtest_experiment_report_artifacts",
]
