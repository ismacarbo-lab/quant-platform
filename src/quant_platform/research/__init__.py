"""Research dataset queries. Not ingestion, strategies, or trading.

This package reads silver tables already stored in PostgreSQL. It does not
download vendors, apply corporate actions, or emit signals.
"""

from quant_platform.research.catalog import (
    compare_dataset_snapshots,
    get_dataset_snapshot_by_id,
    get_dataset_snapshot_by_manifest_hash,
    list_dataset_snapshots,
    register_dataset_snapshot,
    snapshot_is_reproducible,
    snapshot_is_usable,
    validate_catalog_manifest,
)
from quant_platform.research.catalog_types import (
    DatasetSnapshotCatalogEntry,
    DatasetSnapshotCatalogFilters,
    DatasetSnapshotComparison,
    DatasetSnapshotRegistration,
    build_dataset_snapshot_catalog_filters,
)
from quant_platform.research.datasets import (
    get_corporate_actions_for_dataset,
    get_daily_bars_dataset,
    list_instruments_for_dataset,
)
from quant_platform.research.errors import DatasetErrorCode, DatasetValidationError
from quant_platform.research.export import (
    CORPORATE_ACTION_DATASET_COLUMNS,
    DAILY_BAR_DATASET_COLUMNS,
    write_corporate_actions_csv,
    write_daily_bars_csv,
)
from quant_platform.research.quality import (
    analyze_instrument_coverage,
    get_dataset_quality_report,
    write_dataset_quality_json,
)
from quant_platform.research.quality_types import (
    DatasetCoverageSummary,
    DatasetQualityIssue,
    DatasetQualityReport,
    DatasetQualityRequest,
    InstrumentCoverageSummary,
    IssueSeverity,
    QualityIssueCode,
    build_dataset_quality_request,
)
from quant_platform.research.snapshot_types import (
    DatasetSnapshotManifest,
    DatasetSnapshotRequest,
    DatasetSnapshotResult,
    SnapshotArtifact,
    build_dataset_snapshot_request,
)
from quant_platform.research.snapshots import (
    create_daily_bars_snapshot,
    get_git_commit,
    hash_daily_bars_dataset,
    hash_quality_report,
    write_snapshot_manifest,
)
from quant_platform.research.types import (
    CorporateActionDatasetRow,
    DailyBarDatasetRow,
    DailyBarsDataset,
    DailyBarsDatasetRequest,
    build_daily_bars_dataset_request,
)

__all__ = [
    "CORPORATE_ACTION_DATASET_COLUMNS",
    "DAILY_BAR_DATASET_COLUMNS",
    "CorporateActionDatasetRow",
    "DailyBarDatasetRow",
    "DailyBarsDataset",
    "DailyBarsDatasetRequest",
    "DatasetCoverageSummary",
    "DatasetErrorCode",
    "DatasetQualityIssue",
    "DatasetQualityReport",
    "DatasetQualityRequest",
    "DatasetSnapshotCatalogEntry",
    "DatasetSnapshotCatalogFilters",
    "DatasetSnapshotComparison",
    "DatasetSnapshotManifest",
    "DatasetSnapshotRegistration",
    "DatasetSnapshotRequest",
    "DatasetSnapshotResult",
    "DatasetValidationError",
    "InstrumentCoverageSummary",
    "IssueSeverity",
    "QualityIssueCode",
    "SnapshotArtifact",
    "analyze_instrument_coverage",
    "build_daily_bars_dataset_request",
    "build_dataset_quality_request",
    "build_dataset_snapshot_catalog_filters",
    "build_dataset_snapshot_request",
    "compare_dataset_snapshots",
    "create_daily_bars_snapshot",
    "get_corporate_actions_for_dataset",
    "get_daily_bars_dataset",
    "get_dataset_quality_report",
    "get_dataset_snapshot_by_id",
    "get_dataset_snapshot_by_manifest_hash",
    "get_git_commit",
    "hash_daily_bars_dataset",
    "hash_quality_report",
    "list_dataset_snapshots",
    "list_instruments_for_dataset",
    "register_dataset_snapshot",
    "snapshot_is_reproducible",
    "snapshot_is_usable",
    "validate_catalog_manifest",
    "write_corporate_actions_csv",
    "write_daily_bars_csv",
    "write_dataset_quality_json",
    "write_snapshot_manifest",
]
