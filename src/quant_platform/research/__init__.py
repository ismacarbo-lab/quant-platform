"""Research dataset queries. Not ingestion, strategies, or trading.

This package reads silver tables already stored in PostgreSQL. It does not
download vendors, apply corporate actions, or emit signals.
"""

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
    "DatasetValidationError",
    "InstrumentCoverageSummary",
    "IssueSeverity",
    "QualityIssueCode",
    "analyze_instrument_coverage",
    "build_daily_bars_dataset_request",
    "build_dataset_quality_request",
    "get_corporate_actions_for_dataset",
    "get_daily_bars_dataset",
    "get_dataset_quality_report",
    "list_instruments_for_dataset",
    "write_corporate_actions_csv",
    "write_daily_bars_csv",
    "write_dataset_quality_json",
]
