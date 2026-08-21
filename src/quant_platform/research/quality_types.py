"""Typed dataset quality report shapes. Dataclasses, not Pydantic."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from quant_platform.research.errors import DatasetErrorCode, DatasetValidationError
from quant_platform.research.types import (
    DailyBarsDatasetRequest,
    build_daily_bars_dataset_request,
)


class IssueSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class QualityIssueCode(StrEnum):
    MISSING_CALENDAR = "missing_calendar"
    NO_SESSIONS_IN_RANGE = "no_sessions_in_range"
    OPEN_SESSION_WITHOUT_BAR = "open_session_without_bar"
    BAR_ON_HOLIDAY = "bar_on_holiday"
    BAR_ON_EXCEPTIONAL_CLOSE = "bar_on_exceptional_close"
    BAR_ON_UNKNOWN_SESSION = "bar_on_unknown_session"
    LONG_GAP = "long_gap"
    MULTIPLE_SOURCES_SAME_DAY = "multiple_sources_same_day"
    MULTIPLE_VERSIONS_AS_OF = "multiple_versions_as_of"
    CORRECTION_VISIBLE = "correction_visible"
    LOOKAHEAD = "lookahead"
    INGESTION_REJECTIONS = "ingestion_rejections"
    INGESTION_ERROR = "ingestion_error"
    CORPORATE_ACTION_VISIBLE = "corporate_action_visible"


SEVERITY_RANK: dict[str, int] = {
    IssueSeverity.ERROR.value: 0,
    IssueSeverity.WARNING.value: 1,
    IssueSeverity.INFO.value: 2,
}

ISSUE_MAPPING_COLUMNS: tuple[str, ...] = (
    "severity",
    "code",
    "message",
    "instrument_id",
    "symbol",
    "exchange_code",
    "observation_time",
    "source_name",
    "metadata",
)

_MIN_DT = datetime.min.replace(tzinfo=UTC)


def jsonable(value: object) -> object:
    """Convert report values to JSON-native types."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, Mapping):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return [jsonable(item) for item in value]
    return str(value)


@dataclass(frozen=True, slots=True)
class DatasetQualityRequest:
    """Quality diagnostics over a dataset query. ``as_of`` is mandatory."""

    dataset: DailyBarsDatasetRequest
    strict_calendar: bool = False
    long_gap_open_sessions: int = 5


def build_dataset_quality_request(
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
    strict_calendar: bool = False,
    long_gap_open_sessions: int = 5,
) -> DatasetQualityRequest:
    dataset = build_daily_bars_dataset_request(
        as_of=as_of,
        start_time=start_time,
        end_time=end_time,
        symbols=symbols,
        instrument_ids=instrument_ids,
        exchange_codes=exchange_codes,
        asset_classes=asset_classes,
        currency=currency,
        calendar_code=calendar_code,
        require_open_session=require_open_session,
        allow_unfiltered=allow_unfiltered,
    )
    if long_gap_open_sessions < 1:
        raise DatasetValidationError(
            "long_gap_open_sessions must be >= 1",
            code=DatasetErrorCode.INVALID_RANGE,
        )
    return DatasetQualityRequest(
        dataset=dataset,
        strict_calendar=strict_calendar,
        long_gap_open_sessions=long_gap_open_sessions,
    )


@dataclass(frozen=True, slots=True)
class DatasetQualityIssue:
    severity: str
    code: str
    message: str
    instrument_id: UUID | None = None
    symbol: str | None = None
    exchange_code: str | None = None
    observation_time: datetime | None = None
    source_name: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    def as_mapping(self) -> dict[str, object]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "instrument_id": jsonable(self.instrument_id),
            "symbol": self.symbol,
            "exchange_code": self.exchange_code,
            "observation_time": jsonable(self.observation_time),
            "source_name": self.source_name,
            "metadata": jsonable(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class InstrumentCoverageSummary:
    instrument_id: UUID
    symbol: str
    exchange_code: str | None
    asset_class: str
    currency: str | None
    calendar_code: str | None
    first_observation: datetime | None
    last_observation: datetime | None
    bar_count: int
    source_names: tuple[str, ...]
    expected_open_sessions: int | None
    missing_open_sessions: int
    bars_on_closed_sessions: int
    bars_on_unknown_sessions: int
    coverage_ratio: Decimal | None
    visible_corrections: int
    has_calendar: bool

    def as_mapping(self) -> dict[str, object]:
        return {
            "instrument_id": str(self.instrument_id),
            "symbol": self.symbol,
            "exchange_code": self.exchange_code,
            "asset_class": self.asset_class,
            "currency": self.currency,
            "calendar_code": self.calendar_code,
            "first_observation": jsonable(self.first_observation),
            "last_observation": jsonable(self.last_observation),
            "bar_count": self.bar_count,
            "source_names": list(self.source_names),
            "expected_open_sessions": self.expected_open_sessions,
            "missing_open_sessions": self.missing_open_sessions,
            "bars_on_closed_sessions": self.bars_on_closed_sessions,
            "bars_on_unknown_sessions": self.bars_on_unknown_sessions,
            "coverage_ratio": jsonable(self.coverage_ratio),
            "visible_corrections": self.visible_corrections,
            "has_calendar": self.has_calendar,
        }


@dataclass(frozen=True, slots=True)
class DatasetCoverageSummary:
    instrument_count: int
    total_bars: int
    source_names: tuple[str, ...]
    first_observation: datetime | None
    last_observation: datetime | None
    expected_open_sessions: int | None
    missing_open_sessions: int
    bars_outside_calendar: int
    coverage_ratio: Decimal | None
    visible_corrections: int
    pit_versions_as_of: int
    correction_links_as_of: int

    def as_mapping(self) -> dict[str, object]:
        return {
            "instrument_count": self.instrument_count,
            "total_bars": self.total_bars,
            "source_names": list(self.source_names),
            "first_observation": jsonable(self.first_observation),
            "last_observation": jsonable(self.last_observation),
            "expected_open_sessions": self.expected_open_sessions,
            "missing_open_sessions": self.missing_open_sessions,
            "bars_outside_calendar": self.bars_outside_calendar,
            "coverage_ratio": jsonable(self.coverage_ratio),
            "visible_corrections": self.visible_corrections,
            "pit_versions_as_of": self.pit_versions_as_of,
            "correction_links_as_of": self.correction_links_as_of,
        }


@dataclass(frozen=True, slots=True)
class IngestionRunSummary:
    ingestion_run_id: UUID
    source_name: str
    status: str
    accepted_count: int
    rejected_count: int
    started_at: datetime
    error_count: int

    def as_mapping(self) -> dict[str, object]:
        return {
            "ingestion_run_id": str(self.ingestion_run_id),
            "source_name": self.source_name,
            "status": self.status,
            "accepted_count": self.accepted_count,
            "rejected_count": self.rejected_count,
            "started_at": self.started_at.isoformat(),
            "error_count": self.error_count,
        }


@dataclass(frozen=True, slots=True)
class CorporateActionQualityRow:
    instrument_id: UUID
    symbol: str
    exchange_code: str | None
    action_type: str
    effective_time: datetime
    available_time: datetime
    note: str | None

    def as_mapping(self) -> dict[str, object]:
        return {
            "instrument_id": str(self.instrument_id),
            "symbol": self.symbol,
            "exchange_code": self.exchange_code,
            "action_type": self.action_type,
            "effective_time": self.effective_time.isoformat(),
            "available_time": self.available_time.isoformat(),
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class DatasetQualityReport:
    request: DatasetQualityRequest
    generated_at: datetime
    as_of: datetime
    start_time: datetime
    end_time: datetime
    total_rows: int
    instrument_count: int
    issue_count: int
    error_count: int
    warning_count: int
    info_count: int
    coverage: DatasetCoverageSummary
    instruments: tuple[InstrumentCoverageSummary, ...]
    corporate_actions: tuple[CorporateActionQualityRow, ...]
    ingestion_runs: tuple[IngestionRunSummary, ...]
    issues: tuple[DatasetQualityIssue, ...]

    def as_mapping(self) -> dict[str, object]:
        return {
            "generated_at": self.generated_at.isoformat(),
            "as_of": self.as_of.isoformat(),
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "strict_calendar": self.request.strict_calendar,
            "long_gap_open_sessions": self.request.long_gap_open_sessions,
            "calendar_code": self.request.dataset.calendar_code,
            "total_rows": self.total_rows,
            "instrument_count": self.instrument_count,
            "issue_count": self.issue_count,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "info_count": self.info_count,
            "coverage": self.coverage.as_mapping(),
            "instruments": [row.as_mapping() for row in self.instruments],
            "corporate_actions": [row.as_mapping() for row in self.corporate_actions],
            "ingestion_runs": [row.as_mapping() for row in self.ingestion_runs],
            "issues": [row.as_mapping() for row in self.issues],
        }


def issue_sort_key(issue: DatasetQualityIssue) -> tuple[Any, ...]:
    return (
        issue.symbol or "",
        str(issue.instrument_id or ""),
        issue.observation_time or _MIN_DT,
        issue.source_name or "",
        SEVERITY_RANK.get(issue.severity, 9),
        issue.code,
        issue.message,
    )


def count_severities(issues: Sequence[DatasetQualityIssue]) -> tuple[int, int, int]:
    errors = sum(1 for item in issues if item.severity == IssueSeverity.ERROR)
    warnings = sum(1 for item in issues if item.severity == IssueSeverity.WARNING)
    infos = sum(1 for item in issues if item.severity == IssueSeverity.INFO)
    return errors, warnings, infos
