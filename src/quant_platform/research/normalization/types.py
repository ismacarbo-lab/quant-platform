"""Typed corporate-action normalization shapes. Not a strategy API."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from quant_platform.data.validation import DataValidationError, ensure_utc
from quant_platform.research.errors import DatasetErrorCode, DatasetValidationError
from quant_platform.research.normalization.errors import (
    NormalizationError,
    NormalizationErrorCode,
)
from quant_platform.research.types import (
    CorporateActionDatasetRow,
    DailyBarsDataset,
    DailyBarsDatasetRequest,
    build_daily_bars_dataset_request,
)


class AdjustmentMode(StrEnum):
    NONE = "none"
    SPLIT_ONLY = "split_only"
    SPLIT_AND_REVERSE_SPLIT = "split_and_reverse_split"
    INFORMATIONAL = "informational"
    # Splits, reverse splits and cash dividends reinvested on the ex-date
    # (ADR 0005). Derived view only; silver bars stay unadjusted.
    TOTAL_RETURN = "total_return"


DEFAULT_ADJUSTMENT_MODE = AdjustmentMode.SPLIT_ONLY

NORMALIZED_DAILY_BAR_COLUMNS: tuple[str, ...] = (
    "instrument_id",
    "symbol",
    "source_name",
    "observation_time",
    "available_time",
    "as_of",
    "raw_open",
    "raw_high",
    "raw_low",
    "raw_close",
    "raw_volume",
    "normalized_open",
    "normalized_high",
    "normalized_low",
    "normalized_close",
    "normalized_volume",
    "price_factor",
    "volume_factor",
    "applied_action_ids",
    "trace_id",
)

BARS_ARTIFACT_NAME = "normalized_daily_bars.csv"
REPORT_ARTIFACT_NAME = "normalization_report.json"
MANIFEST_ARTIFACT_NAME = "normalization_manifest.json"


def _utc(value: datetime | None, *, field: str) -> datetime:
    if value is None:
        raise NormalizationError(
            f"{field} is required",
            code=NormalizationErrorCode.MISSING_AS_OF
            if field == "as_of"
            else NormalizationErrorCode.INVALID_RANGE,
        )
    try:
        return ensure_utc(value, field=field)
    except DataValidationError as exc:
        raise NormalizationError(
            str(exc), code=NormalizationErrorCode.NAIVE_TIMESTAMP
        ) from exc


def parse_adjustment_mode(value: str | AdjustmentMode) -> AdjustmentMode:
    token = str(value).strip()
    try:
        return AdjustmentMode(token)
    except ValueError as exc:
        raise NormalizationError(
            f"unsupported adjustment_mode {token!r}",
            code=NormalizationErrorCode.INVALID_MODE,
        ) from exc


@dataclass(frozen=True, slots=True)
class CorporateActionFactor:
    action_id: UUID | None
    action_type: str
    instrument_id: UUID
    effective_time: datetime
    available_time: datetime
    price_factor: Decimal
    volume_factor: Decimal
    applied: bool
    note: str | None = None

    def as_mapping(self) -> dict[str, object]:
        return {
            "action_id": None if self.action_id is None else str(self.action_id),
            "action_type": self.action_type,
            "instrument_id": str(self.instrument_id),
            "effective_time": self.effective_time,
            "available_time": self.available_time,
            "price_factor": self.price_factor,
            "volume_factor": self.volume_factor,
            "applied": self.applied,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class NormalizationRequest:
    as_of: datetime
    start_time: datetime
    end_time: datetime
    source_name: str
    adjustment_mode: AdjustmentMode = DEFAULT_ADJUSTMENT_MODE
    symbols: tuple[str, ...] | None = None
    instrument_ids: tuple[UUID, ...] | None = None
    exchange_codes: tuple[str, ...] | None = None
    asset_classes: tuple[str, ...] | None = None
    currency: str | None = None
    calendar_code: str | None = None
    require_open_session: bool = False
    allow_unfiltered: bool = False

    def dataset_request(self) -> DailyBarsDatasetRequest:
        return build_daily_bars_dataset_request(
            as_of=self.as_of,
            start_time=self.start_time,
            end_time=self.end_time,
            symbols=self.symbols,
            instrument_ids=self.instrument_ids,
            exchange_codes=self.exchange_codes,
            asset_classes=self.asset_classes,
            currency=self.currency,
            calendar_code=self.calendar_code,
            require_open_session=self.require_open_session,
            allow_unfiltered=self.allow_unfiltered,
        )


def build_normalization_request(
    *,
    as_of: datetime | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    source_name: str | None = None,
    adjustment_mode: str | AdjustmentMode = DEFAULT_ADJUSTMENT_MODE,
    symbols: Sequence[str] | None = None,
    instrument_ids: Sequence[UUID] | None = None,
    exchange_codes: Sequence[str] | None = None,
    asset_classes: Sequence[str] | None = None,
    currency: str | None = None,
    calendar_code: str | None = None,
    require_open_session: bool = False,
    allow_unfiltered: bool = False,
) -> NormalizationRequest:
    """Validate a derived-dataset request. Does not query PostgreSQL."""
    source = (source_name or "").strip()
    if not source:
        raise NormalizationError(
            "source_name is required",
            code=NormalizationErrorCode.MISSING_SOURCE,
        )
    mode = parse_adjustment_mode(adjustment_mode)
    as_of_utc = _utc(as_of, field="as_of")
    start_utc = _utc(start_time, field="start_time")
    end_utc = _utc(end_time, field="end_time")
    if start_utc > end_utc:
        raise NormalizationError(
            "start_time must be <= end_time",
            code=NormalizationErrorCode.INVALID_RANGE,
        )
    try:
        dataset = build_daily_bars_dataset_request(
            as_of=as_of_utc,
            start_time=start_utc,
            end_time=end_utc,
            symbols=symbols,
            instrument_ids=instrument_ids,
            exchange_codes=exchange_codes,
            asset_classes=asset_classes,
            currency=currency,
            calendar_code=calendar_code,
            require_open_session=require_open_session,
            allow_unfiltered=allow_unfiltered,
        )
    except DatasetValidationError as exc:
        code = (
            NormalizationErrorCode.MISSING_AS_OF
            if exc.code == DatasetErrorCode.MISSING_AS_OF
            else NormalizationErrorCode.EMPTY_FILTER
            if exc.code == DatasetErrorCode.EMPTY_FILTER
            else NormalizationErrorCode.NAIVE_TIMESTAMP
            if exc.code == DatasetErrorCode.NAIVE_TIMESTAMP
            else NormalizationErrorCode.INVALID_RANGE
        )
        raise NormalizationError(str(exc), code=code) from exc
    return NormalizationRequest(
        as_of=dataset.as_of,
        start_time=dataset.start_time,
        end_time=dataset.end_time,
        source_name=source,
        adjustment_mode=mode,
        symbols=dataset.symbols,
        instrument_ids=dataset.instrument_ids,
        exchange_codes=dataset.exchange_codes,
        asset_classes=dataset.asset_classes,
        currency=dataset.currency,
        calendar_code=dataset.calendar_code,
        require_open_session=dataset.require_open_session,
        allow_unfiltered=dataset.allow_unfiltered,
    )


@dataclass(frozen=True, slots=True)
class NormalizationIssue:
    code: str
    message: str
    severity: str = "warning"
    instrument_id: UUID | None = None
    action_id: UUID | None = None

    def as_mapping(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
            "instrument_id": None
            if self.instrument_id is None
            else str(self.instrument_id),
            "action_id": None if self.action_id is None else str(self.action_id),
        }


@dataclass(frozen=True, slots=True)
class NormalizationAdjustmentTrace:
    trace_id: str
    instrument_id: UUID
    symbol: str
    source_name: str
    observation_time: datetime
    available_time: datetime
    as_of: datetime
    adjustment_mode: str
    price_factor: Decimal
    volume_factor: Decimal
    applied_action_ids: tuple[str, ...]
    factors: tuple[CorporateActionFactor, ...]
    issue_codes: tuple[str, ...]

    def as_mapping(self) -> dict[str, object]:
        return {
            "trace_id": self.trace_id,
            "instrument_id": str(self.instrument_id),
            "symbol": self.symbol,
            "source_name": self.source_name,
            "observation_time": self.observation_time,
            "available_time": self.available_time,
            "as_of": self.as_of,
            "adjustment_mode": self.adjustment_mode,
            "price_factor": self.price_factor,
            "volume_factor": self.volume_factor,
            "applied_action_ids": list(self.applied_action_ids),
            "factors": [item.as_mapping() for item in self.factors],
            "issue_codes": list(self.issue_codes),
        }


@dataclass(frozen=True, slots=True)
class NormalizedDailyBar:
    instrument_id: UUID
    symbol: str
    source_name: str
    observation_time: datetime
    available_time: datetime
    as_of: datetime
    raw_open: Decimal
    raw_high: Decimal
    raw_low: Decimal
    raw_close: Decimal
    raw_volume: Decimal | None
    normalized_open: Decimal
    normalized_high: Decimal
    normalized_low: Decimal
    normalized_close: Decimal
    normalized_volume: Decimal | None
    price_factor: Decimal
    volume_factor: Decimal
    applied_action_ids: tuple[str, ...]
    trace_id: str

    def as_mapping(self) -> dict[str, object]:
        return {
            "instrument_id": str(self.instrument_id),
            "symbol": self.symbol,
            "source_name": self.source_name,
            "observation_time": self.observation_time,
            "available_time": self.available_time,
            "as_of": self.as_of,
            "raw_open": self.raw_open,
            "raw_high": self.raw_high,
            "raw_low": self.raw_low,
            "raw_close": self.raw_close,
            "raw_volume": self.raw_volume,
            "normalized_open": self.normalized_open,
            "normalized_high": self.normalized_high,
            "normalized_low": self.normalized_low,
            "normalized_close": self.normalized_close,
            "normalized_volume": self.normalized_volume,
            "price_factor": self.price_factor,
            "volume_factor": self.volume_factor,
            "applied_action_ids": list(self.applied_action_ids),
            "trace_id": self.trace_id,
        }

    def as_csv_row(self) -> dict[str, str]:
        return {
            "instrument_id": str(self.instrument_id),
            "symbol": self.symbol,
            "source_name": self.source_name,
            "observation_time": self.observation_time.isoformat(),
            "available_time": self.available_time.isoformat(),
            "as_of": self.as_of.isoformat(),
            "raw_open": format(self.raw_open, "f"),
            "raw_high": format(self.raw_high, "f"),
            "raw_low": format(self.raw_low, "f"),
            "raw_close": format(self.raw_close, "f"),
            "raw_volume": ""
            if self.raw_volume is None
            else format(self.raw_volume, "f"),
            "normalized_open": format(self.normalized_open, "f"),
            "normalized_high": format(self.normalized_high, "f"),
            "normalized_low": format(self.normalized_low, "f"),
            "normalized_close": format(self.normalized_close, "f"),
            "normalized_volume": (
                ""
                if self.normalized_volume is None
                else format(self.normalized_volume, "f")
            ),
            "price_factor": format(self.price_factor, "f"),
            "volume_factor": format(self.volume_factor, "f"),
            "applied_action_ids": ";".join(self.applied_action_ids),
            "trace_id": self.trace_id,
        }


@dataclass(frozen=True, slots=True)
class NormalizationReport:
    ok: bool
    as_of: datetime
    adjustment_mode: str
    source_name: str
    bar_count: int
    raw_bar_count: int
    visible_action_count: int
    applied_action_count: int
    issue_count: int
    warning_count: int
    error_count: int
    dataset_hash: str
    raw_dataset_hash: str
    issues: tuple[NormalizationIssue, ...]
    applied_actions: tuple[CorporateActionFactor, ...]

    def as_mapping(self) -> dict[str, object]:
        return {
            "kind": "normalization_report",
            "ok": self.ok,
            "as_of": self.as_of,
            "adjustment_mode": self.adjustment_mode,
            "source_name": self.source_name,
            "bar_count": self.bar_count,
            "raw_bar_count": self.raw_bar_count,
            "visible_action_count": self.visible_action_count,
            "applied_action_count": self.applied_action_count,
            "issue_count": self.issue_count,
            "warning_count": self.warning_count,
            "error_count": self.error_count,
            "dataset_hash": self.dataset_hash,
            "raw_dataset_hash": self.raw_dataset_hash,
            "issues": [item.as_mapping() for item in self.issues],
            "applied_actions": [item.as_mapping() for item in self.applied_actions],
        }


@dataclass(frozen=True, slots=True)
class NormalizationArtifact:
    name: str
    path: str
    kind: str

    def as_mapping(self) -> dict[str, object]:
        return {"name": self.name, "path": self.path, "kind": self.kind}


@dataclass(frozen=True, slots=True)
class NormalizationManifest:
    kind: str
    format_version: int
    as_of: datetime
    adjustment_mode: str
    source_name: str
    dataset_hash: str
    raw_dataset_hash: str
    bar_count: int
    applied_action_count: int
    issue_count: int
    warning_count: int
    error_count: int
    artifacts: tuple[NormalizationArtifact, ...]
    applied_actions_summary: tuple[dict[str, object], ...]
    package_version: str
    git_commit: str | None = None
    created_at: datetime | None = None

    def as_mapping(self, *, include_created_at: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "kind": self.kind,
            "format_version": self.format_version,
            "as_of": self.as_of,
            "adjustment_mode": self.adjustment_mode,
            "source_name": self.source_name,
            "dataset_hash": self.dataset_hash,
            "raw_dataset_hash": self.raw_dataset_hash,
            "bar_count": self.bar_count,
            "applied_action_count": self.applied_action_count,
            "issue_count": self.issue_count,
            "warning_count": self.warning_count,
            "error_count": self.error_count,
            "artifacts": [item.as_mapping() for item in self.artifacts],
            "applied_actions_summary": list(self.applied_actions_summary),
            "package_version": self.package_version,
            "git_commit": self.git_commit,
        }
        if include_created_at:
            payload["created_at"] = self.created_at
        return payload


@dataclass(frozen=True, slots=True)
class NormalizedDailyBarsDataset:
    request: NormalizationRequest
    raw_dataset: DailyBarsDataset
    rows: tuple[NormalizedDailyBar, ...]
    traces: tuple[NormalizationAdjustmentTrace, ...]
    visible_actions: tuple[CorporateActionDatasetRow, ...]
    report: NormalizationReport
    dataset_hash: str
    raw_dataset_hash: str

    def __iter__(self) -> Iterator[NormalizedDailyBar]:
        return iter(self.rows)

    def __len__(self) -> int:
        return len(self.rows)
