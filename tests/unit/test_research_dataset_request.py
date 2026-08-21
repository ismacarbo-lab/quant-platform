"""Dataset request validation and CSV serialization without a database."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from quant_platform.research.datasets import validate_dataset_bar_row
from quant_platform.research.errors import DatasetErrorCode, DatasetValidationError
from quant_platform.research.export import write_daily_bars_csv
from quant_platform.research.types import (
    DAILY_BAR_DATASET_COLUMNS,
    DailyBarDatasetRow,
    DailyBarsDatasetRequest,
    build_daily_bars_dataset_request,
)


def _request_kwargs(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "as_of": datetime(2024, 1, 10, tzinfo=UTC),
        "start_time": datetime(2024, 1, 1, tzinfo=UTC),
        "end_time": datetime(2024, 1, 5, tzinfo=UTC),
        "symbols": ["FICT"],
    }
    base.update(overrides)
    return base


def test_request_requires_as_of() -> None:
    with pytest.raises(DatasetValidationError, match="as_of is required") as exc:
        build_daily_bars_dataset_request(
            start_time=datetime(2024, 1, 1, tzinfo=UTC),
            end_time=datetime(2024, 1, 5, tzinfo=UTC),
            symbols=["FICT"],
        )
    assert exc.value.code == DatasetErrorCode.MISSING_AS_OF


def test_request_rejects_naive_timestamps() -> None:
    with pytest.raises(DatasetValidationError, match="timezone-aware") as exc:
        build_daily_bars_dataset_request(**_request_kwargs(as_of=datetime(2024, 1, 10)))
    assert exc.value.code == DatasetErrorCode.NAIVE_TIMESTAMP


def test_request_rejects_inverted_range() -> None:
    with pytest.raises(DatasetValidationError, match="start_time must be") as exc:
        build_daily_bars_dataset_request(
            **_request_kwargs(
                start_time=datetime(2024, 1, 10, tzinfo=UTC),
                end_time=datetime(2024, 1, 1, tzinfo=UTC),
            )
        )
    assert exc.value.code == DatasetErrorCode.INVALID_RANGE


def test_request_rejects_unbounded_query() -> None:
    with pytest.raises(DatasetValidationError, match="identity filter") as exc:
        build_daily_bars_dataset_request(
            as_of=datetime(2024, 1, 10, tzinfo=UTC),
            start_time=datetime(2024, 1, 1, tzinfo=UTC),
            end_time=datetime(2024, 1, 5, tzinfo=UTC),
        )
    assert exc.value.code == DatasetErrorCode.UNBOUNDED_QUERY


def test_request_allow_unfiltered_is_explicit() -> None:
    request = build_daily_bars_dataset_request(
        as_of=datetime(2024, 1, 10, tzinfo=UTC),
        start_time=datetime(2024, 1, 1, tzinfo=UTC),
        end_time=datetime(2024, 1, 5, tzinfo=UTC),
        allow_unfiltered=True,
    )
    assert request.allow_unfiltered is True
    assert request.symbols is None


def test_request_empty_symbol_filter_is_rejected() -> None:
    with pytest.raises(
        DatasetValidationError, match="symbols must not be empty"
    ) as exc:
        build_daily_bars_dataset_request(**_request_kwargs(symbols=["  "]))
    assert exc.value.code == DatasetErrorCode.EMPTY_FILTER


def test_request_open_session_needs_calendar_code() -> None:
    with pytest.raises(DatasetValidationError, match="calendar_code") as exc:
        build_daily_bars_dataset_request(
            **_request_kwargs(require_open_session=True, calendar_code=None)
        )
    assert exc.value.code == DatasetErrorCode.CALENDAR_REQUIRED


def test_row_serialization_uses_stable_columns() -> None:
    row = DailyBarDatasetRow(
        instrument_id=uuid4(),
        symbol="FICT",
        exchange_code="XNYS",
        asset_class="equity",
        currency="USD",
        observation_time=datetime(2024, 1, 2, tzinfo=UTC),
        available_time=datetime(2024, 1, 3, tzinfo=UTC),
        open=Decimal("10"),
        high=Decimal("11"),
        low=Decimal("9"),
        close=Decimal("10.5"),
        volume=Decimal("1000"),
        source_name="local_csv",
        ingestion_run_id=uuid4(),
        is_correction=False,
        correction_reason=None,
    )
    mapping = row.as_mapping()
    csv_row = row.as_csv_row()
    assert tuple(mapping) == DAILY_BAR_DATASET_COLUMNS
    assert tuple(csv_row) == DAILY_BAR_DATASET_COLUMNS
    assert csv_row["is_correction"] == "false"
    assert csv_row["volume"] == "1000"
    assert csv_row["correction_reason"] == ""


def test_csv_export_writes_header_and_row(tmp_path: Path) -> None:
    row = DailyBarDatasetRow(
        instrument_id=uuid4(),
        symbol="FICT",
        exchange_code=None,
        asset_class="equity",
        currency=None,
        observation_time=datetime(2024, 1, 2, tzinfo=UTC),
        available_time=datetime(2024, 1, 3, tzinfo=UTC),
        open=Decimal("1"),
        high=Decimal("1"),
        low=Decimal("1"),
        close=Decimal("1"),
        volume=None,
        source_name="local_csv",
        ingestion_run_id=uuid4(),
        is_correction=True,
        correction_reason="restated",
    )
    path = tmp_path / "dataset.csv"
    assert write_daily_bars_csv([row], path) == 1
    text = path.read_text(encoding="utf-8")
    assert text.splitlines()[0] == ",".join(DAILY_BAR_DATASET_COLUMNS)
    assert "true" in text
    assert "restated" in text


def test_validate_dataset_bar_row_rejects_lookahead() -> None:
    request = build_daily_bars_dataset_request(**_request_kwargs())
    row = DailyBarDatasetRow(
        instrument_id=uuid4(),
        symbol="FICT",
        exchange_code="XNYS",
        asset_class="equity",
        currency="USD",
        observation_time=datetime(2024, 1, 2, tzinfo=UTC),
        available_time=datetime(2024, 2, 1, tzinfo=UTC),
        open=Decimal("10"),
        high=Decimal("11"),
        low=Decimal("9"),
        close=Decimal("10"),
        volume=None,
        source_name="local_csv",
        ingestion_run_id=uuid4(),
        is_correction=False,
        correction_reason=None,
    )
    with pytest.raises(DatasetValidationError, match="available_time must be") as exc:
        validate_dataset_bar_row(row, request=request)
    assert exc.value.code == DatasetErrorCode.LOOKAHEAD


def test_direct_request_construction_is_still_revalidated() -> None:
    request = DailyBarsDatasetRequest(
        as_of=datetime(2024, 1, 10),
        start_time=datetime(2024, 1, 1, tzinfo=UTC),
        end_time=datetime(2024, 1, 5, tzinfo=UTC),
        symbols=("FICT",),
    )
    with pytest.raises(DatasetValidationError) as exc:
        build_daily_bars_dataset_request(
            as_of=request.as_of,
            start_time=request.start_time,
            end_time=request.end_time,
            symbols=request.symbols,
        )
    assert exc.value.code == DatasetErrorCode.NAIVE_TIMESTAMP
