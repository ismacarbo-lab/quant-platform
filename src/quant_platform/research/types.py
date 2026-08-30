"""Typed dataset request and row shapes. Dataclasses, not Pydantic."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from quant_platform.data.validation import DataValidationError, ensure_utc
from quant_platform.research.errors import DatasetErrorCode, DatasetValidationError

DAILY_BAR_DATASET_COLUMNS: tuple[str, ...] = (
    "instrument_id",
    "symbol",
    "exchange_code",
    "asset_class",
    "currency",
    "observation_time",
    "available_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "source_name",
    "ingestion_run_id",
    "is_correction",
    "correction_reason",
)

CORPORATE_ACTION_DATASET_COLUMNS: tuple[str, ...] = (
    "instrument_id",
    "symbol",
    "exchange_code",
    "asset_class",
    "action_type",
    "effective_time",
    "available_time",
    "quantity_before",
    "quantity_after",
    "cash_amount",
    "currency",
    "old_value",
    "new_value",
    "note",
)


def _utc(value: datetime | None, *, field: str) -> datetime:
    if value is None:
        code = (
            DatasetErrorCode.MISSING_AS_OF
            if field == "as_of"
            else DatasetErrorCode.INVALID_RANGE
        )
        raise DatasetValidationError(f"{field} is required", code=code)
    try:
        return ensure_utc(value, field=field)
    except DataValidationError as exc:
        raise DatasetValidationError(
            str(exc), code=DatasetErrorCode.NAIVE_TIMESTAMP
        ) from exc


def _optional_str(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _unique_strings(
    values: Sequence[str] | None, *, field: str
) -> tuple[str, ...] | None:
    if values is None:
        return None
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in values:
        token = item.strip()
        if not token or token in seen:
            continue
        seen.add(token)
        cleaned.append(token)
    if not cleaned:
        raise DatasetValidationError(
            f"{field} must not be empty",
            code=DatasetErrorCode.EMPTY_FILTER,
        )
    return tuple(cleaned)


def _unique_ids(
    values: Sequence[UUID] | None, *, field: str
) -> tuple[UUID, ...] | None:
    if values is None:
        return None
    cleaned: list[UUID] = []
    seen: set[UUID] = set()
    for item in values:
        if item in seen:
            continue
        seen.add(item)
        cleaned.append(item)
    if not cleaned:
        raise DatasetValidationError(
            f"{field} must not be empty",
            code=DatasetErrorCode.EMPTY_FILTER,
        )
    return tuple(cleaned)


@dataclass(frozen=True, slots=True)
class DailyBarsDatasetRequest:
    """Deterministic daily-bar dataset query. ``as_of`` is mandatory."""

    as_of: datetime
    start_time: datetime
    end_time: datetime
    symbols: tuple[str, ...] | None = None
    instrument_ids: tuple[UUID, ...] | None = None
    exchange_codes: tuple[str, ...] | None = None
    asset_classes: tuple[str, ...] | None = None
    currency: str | None = None
    calendar_code: str | None = None
    require_open_session: bool = False
    allow_unfiltered: bool = False

    def uses_calendar(self) -> bool:
        return self.calendar_code is not None or self.require_open_session


def build_daily_bars_dataset_request(
    *,
    as_of: datetime | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    symbols: Sequence[str] | None = None,
    instrument_ids: Sequence[UUID] | None = None,
    exchange_codes: Sequence[str] | None = None,
    asset_classes: Sequence[str] | None = None,
    currency: str | None = None,
    calendar_code: str | None = None,
    require_open_session: bool = False,
    allow_unfiltered: bool = False,
) -> DailyBarsDatasetRequest:
    """Validate and normalize a dataset query.

    There is no implicit ``latest=True``. Missing ``as_of`` is always an error.
    """
    as_of_utc = _utc(as_of, field="as_of")
    start_utc = _utc(start_time, field="start_time")
    end_utc = _utc(end_time, field="end_time")
    if start_utc > end_utc:
        raise DatasetValidationError(
            "start_time must be <= end_time",
            code=DatasetErrorCode.INVALID_RANGE,
        )
    calendar = _optional_str(calendar_code)
    if require_open_session and calendar is None:
        raise DatasetValidationError(
            "require_open_session needs calendar_code; calendars are not inferred",
            code=DatasetErrorCode.CALENDAR_REQUIRED,
        )
    request = DailyBarsDatasetRequest(
        as_of=as_of_utc,
        start_time=start_utc,
        end_time=end_utc,
        symbols=_unique_strings(symbols, field="symbols"),
        instrument_ids=_unique_ids(instrument_ids, field="instrument_ids"),
        exchange_codes=_unique_strings(exchange_codes, field="exchange_codes"),
        asset_classes=_unique_strings(asset_classes, field="asset_classes"),
        currency=_optional_str(currency),
        calendar_code=calendar,
        require_open_session=require_open_session,
        allow_unfiltered=allow_unfiltered,
    )
    if not _has_identity_filter(request) and not request.allow_unfiltered:
        raise DatasetValidationError(
            "dataset query needs an identity filter or allow_unfiltered=True",
            code=DatasetErrorCode.UNBOUNDED_QUERY,
        )
    return request


def _has_identity_filter(request: DailyBarsDatasetRequest) -> bool:
    return any(
        (
            request.symbols is not None,
            request.instrument_ids is not None,
            request.exchange_codes is not None,
            request.asset_classes is not None,
            request.currency is not None,
        )
    )


def _fmt_decimal(value: Decimal | None) -> str:
    if value is None:
        return ""
    return format(value, "f")


def _fmt_dt(value: datetime) -> str:
    return value.isoformat()


@dataclass(frozen=True, slots=True)
class DailyBarDatasetRow:
    instrument_id: UUID
    symbol: str
    exchange_code: str | None
    asset_class: str
    currency: str | None
    observation_time: datetime
    available_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None
    source_name: str
    ingestion_run_id: UUID
    is_correction: bool
    correction_reason: str | None

    def as_mapping(self) -> dict[str, object]:
        return {
            "instrument_id": self.instrument_id,
            "symbol": self.symbol,
            "exchange_code": self.exchange_code,
            "asset_class": self.asset_class,
            "currency": self.currency,
            "observation_time": self.observation_time,
            "available_time": self.available_time,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "source_name": self.source_name,
            "ingestion_run_id": self.ingestion_run_id,
            "is_correction": self.is_correction,
            "correction_reason": self.correction_reason,
        }

    def as_csv_row(self) -> dict[str, str]:
        return {
            "instrument_id": str(self.instrument_id),
            "symbol": self.symbol,
            "exchange_code": self.exchange_code or "",
            "asset_class": self.asset_class,
            "currency": self.currency or "",
            "observation_time": _fmt_dt(self.observation_time),
            "available_time": _fmt_dt(self.available_time),
            "open": _fmt_decimal(self.open),
            "high": _fmt_decimal(self.high),
            "low": _fmt_decimal(self.low),
            "close": _fmt_decimal(self.close),
            "volume": _fmt_decimal(self.volume),
            "source_name": self.source_name,
            "ingestion_run_id": str(self.ingestion_run_id),
            "is_correction": "true" if self.is_correction else "false",
            "correction_reason": self.correction_reason or "",
        }


@dataclass(frozen=True, slots=True)
class DailyBarsDataset:
    request: DailyBarsDatasetRequest
    rows: tuple[DailyBarDatasetRow, ...]

    def __iter__(self) -> Iterator[DailyBarDatasetRow]:
        return iter(self.rows)

    def __len__(self) -> int:
        return len(self.rows)


@dataclass(frozen=True, slots=True)
class CorporateActionDatasetRow:
    instrument_id: UUID
    symbol: str
    exchange_code: str | None
    asset_class: str
    action_type: str
    effective_time: datetime
    available_time: datetime
    quantity_before: Decimal | None
    quantity_after: Decimal | None
    cash_amount: Decimal | None
    currency: str | None
    old_value: str | None
    new_value: str | None
    note: str | None
    id: UUID | None = None

    def as_mapping(self) -> dict[str, object]:
        return {
            "id": self.id,
            "instrument_id": self.instrument_id,
            "symbol": self.symbol,
            "exchange_code": self.exchange_code,
            "asset_class": self.asset_class,
            "action_type": self.action_type,
            "effective_time": self.effective_time,
            "available_time": self.available_time,
            "quantity_before": self.quantity_before,
            "quantity_after": self.quantity_after,
            "cash_amount": self.cash_amount,
            "currency": self.currency,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "note": self.note,
        }

    def as_csv_row(self) -> dict[str, str]:
        return {
            "instrument_id": str(self.instrument_id),
            "symbol": self.symbol,
            "exchange_code": self.exchange_code or "",
            "asset_class": self.asset_class,
            "action_type": self.action_type,
            "effective_time": _fmt_dt(self.effective_time),
            "available_time": _fmt_dt(self.available_time),
            "quantity_before": _fmt_decimal(self.quantity_before),
            "quantity_after": _fmt_decimal(self.quantity_after),
            "cash_amount": _fmt_decimal(self.cash_amount),
            "currency": self.currency or "",
            "old_value": self.old_value or "",
            "new_value": self.new_value or "",
            "note": self.note or "",
        }
