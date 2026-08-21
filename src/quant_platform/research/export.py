"""Local CSV export for research datasets. No Parquet (no pyarrow)."""

from __future__ import annotations

import csv
from collections.abc import Iterable, Sequence
from pathlib import Path

from quant_platform.research.types import (
    CORPORATE_ACTION_DATASET_COLUMNS,
    DAILY_BAR_DATASET_COLUMNS,
    CorporateActionDatasetRow,
    DailyBarDatasetRow,
    DailyBarsDataset,
)

# Re-exported so callers can pin a column contract without importing types.
__all__ = [
    "CORPORATE_ACTION_DATASET_COLUMNS",
    "DAILY_BAR_DATASET_COLUMNS",
    "write_corporate_actions_csv",
    "write_daily_bars_csv",
]


def write_daily_bars_csv(
    rows: DailyBarsDataset | Sequence[DailyBarDatasetRow],
    path: Path,
) -> int:
    """Write daily-bar dataset rows to UTF-8 CSV. Returns the row count."""
    sequence: Iterable[DailyBarDatasetRow]
    if isinstance(rows, DailyBarsDataset):
        sequence = rows.rows
    else:
        sequence = rows
    return _write_csv(
        path,
        columns=DAILY_BAR_DATASET_COLUMNS,
        records=(row.as_csv_row() for row in sequence),
    )


def write_corporate_actions_csv(
    rows: Sequence[CorporateActionDatasetRow],
    path: Path,
) -> int:
    """Write corporate-action dataset rows to UTF-8 CSV. Returns the row count."""
    return _write_csv(
        path,
        columns=CORPORATE_ACTION_DATASET_COLUMNS,
        records=(row.as_csv_row() for row in rows),
    )


def _write_csv(
    path: Path,
    *,
    columns: Sequence[str],
    records: Iterable[dict[str, str]],
) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns), extrasaction="ignore")
        writer.writeheader()
        for record in records:
            writer.writerow(record)
            count += 1
    return count
