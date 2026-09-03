"""Research-only corporate-action normalization. Silver bars are not rewritten.

This package builds a derived daily-bar view. It does not emit decisions,
compute performance, or talk to brokers.
"""

from quant_platform.research.normalization.artifacts import (
    write_normalized_dataset_artifacts,
)
from quant_platform.research.normalization.catalog import (
    build_normalized_dataset_registration,
    compare_normalized_datasets,
    deterministic_normalized_dataset_id,
    evaluate_normalized_dataset_usability,
    get_normalized_dataset_by_id,
    get_normalized_dataset_by_manifest_hash,
    list_normalized_datasets,
    register_normalized_dataset,
)
from quant_platform.research.normalization.catalog_types import (
    NormalizedDatasetCatalogEntry,
    NormalizedDatasetCatalogFilters,
    NormalizedDatasetComparison,
    NormalizedDatasetRegistration,
    NormalizedDatasetUsabilityIssue,
    NormalizedDatasetUsabilityReport,
    build_normalized_dataset_catalog_filters,
)
from quant_platform.research.normalization.datasets import (
    assemble_normalized_dataset,
    build_normalized_daily_bars_dataset,
    hash_normalized_daily_bars_dataset,
)
from quant_platform.research.normalization.errors import (
    NormalizationError,
    NormalizationErrorCode,
)
from quant_platform.research.normalization.factors import (
    compute_bar_adjustment,
    split_quantity_factors,
)
from quant_platform.research.normalization.integrity import (
    NormalizationIntegrityReport,
    verify_normalization_artifacts,
)
from quant_platform.research.normalization.regression import (
    hash_normalization_regression_report,
    run_normalization_regression_matrix,
)
from quant_platform.research.normalization.regression_artifacts import (
    write_normalization_regression_artifacts,
)
from quant_platform.research.normalization.types import (
    AdjustmentMode,
    CorporateActionFactor,
    NormalizationAdjustmentTrace,
    NormalizationArtifact,
    NormalizationIssue,
    NormalizationManifest,
    NormalizationReport,
    NormalizationRequest,
    NormalizedDailyBar,
    NormalizedDailyBarsDataset,
    build_normalization_request,
)

__all__ = [
    "AdjustmentMode",
    "CorporateActionFactor",
    "NormalizationAdjustmentTrace",
    "NormalizationArtifact",
    "NormalizationError",
    "NormalizationErrorCode",
    "NormalizationIntegrityReport",
    "NormalizationIssue",
    "NormalizationManifest",
    "NormalizationReport",
    "NormalizationRequest",
    "NormalizedDailyBar",
    "NormalizedDailyBarsDataset",
    "NormalizedDatasetCatalogEntry",
    "NormalizedDatasetCatalogFilters",
    "NormalizedDatasetComparison",
    "NormalizedDatasetRegistration",
    "NormalizedDatasetUsabilityIssue",
    "NormalizedDatasetUsabilityReport",
    "assemble_normalized_dataset",
    "build_normalization_request",
    "build_normalized_daily_bars_dataset",
    "build_normalized_dataset_catalog_filters",
    "build_normalized_dataset_registration",
    "compare_normalized_datasets",
    "compute_bar_adjustment",
    "deterministic_normalized_dataset_id",
    "evaluate_normalized_dataset_usability",
    "get_normalized_dataset_by_id",
    "get_normalized_dataset_by_manifest_hash",
    "hash_normalization_regression_report",
    "hash_normalized_daily_bars_dataset",
    "list_normalized_datasets",
    "register_normalized_dataset",
    "run_normalization_regression_matrix",
    "split_quantity_factors",
    "verify_normalization_artifacts",
    "write_normalization_regression_artifacts",
    "write_normalized_dataset_artifacts",
]
