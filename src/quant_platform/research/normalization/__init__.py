"""Research-only corporate-action normalization. Silver bars are not rewritten.

This package builds a derived daily-bar view. It does not emit decisions,
compute performance, or talk to brokers.
"""

from quant_platform.research.normalization.artifacts import (
    write_normalized_dataset_artifacts,
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
    "assemble_normalized_dataset",
    "build_normalization_request",
    "build_normalized_daily_bars_dataset",
    "compute_bar_adjustment",
    "hash_normalized_daily_bars_dataset",
    "split_quantity_factors",
    "verify_normalization_artifacts",
    "write_normalized_dataset_artifacts",
]
