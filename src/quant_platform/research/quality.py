"""Dataset quality reports. Consumes the research dataset API; no trading."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from quant_platform.core.time import utc_now
from quant_platform.data.calendar import session_date_for_observation
from quant_platform.data.models import (
    DailyBar,
    DataSource,
    Exchange,
    IngestionRun,
    Instrument,
    MarketCalendar,
    MarketSession,
    SessionKind,
)
from quant_platform.data.repository import (
    get_market_calendar_by_code,
    list_ingestion_errors,
    list_market_sessions,
)
from quant_platform.research.datasets import (
    get_corporate_actions_for_dataset,
    get_daily_bars_dataset,
    list_instruments_for_dataset,
)
from quant_platform.research.errors import DatasetErrorCode, DatasetValidationError
from quant_platform.research.quality_types import (
    CorporateActionQualityRow,
    DatasetCoverageSummary,
    DatasetQualityIssue,
    DatasetQualityReport,
    DatasetQualityRequest,
    IngestionRunSummary,
    InstrumentCoverageSummary,
    IssueSeverity,
    QualityIssueCode,
    build_dataset_quality_request,
    count_severities,
    issue_sort_key,
)
from quant_platform.research.types import (
    DailyBarDatasetRow,
    DailyBarsDatasetRequest,
    build_daily_bars_dataset_request,
)

_COVERAGE_QUANTUM = Decimal("0.0001")


def get_dataset_quality_report(
    session: Session,
    request: DatasetQualityRequest,
    *,
    generated_at: datetime | None = None,
) -> DatasetQualityReport:
    """Build a deterministic quality report for a PIT dataset window."""
    rebuilt = build_dataset_quality_request(
        as_of=request.dataset.as_of,
        start_time=request.dataset.start_time,
        end_time=request.dataset.end_time,
        symbols=request.dataset.symbols,
        instrument_ids=request.dataset.instrument_ids,
        exchange_codes=request.dataset.exchange_codes,
        asset_classes=request.dataset.asset_classes,
        currency=request.dataset.currency,
        calendar_code=request.dataset.calendar_code,
        require_open_session=request.dataset.require_open_session,
        allow_unfiltered=request.dataset.allow_unfiltered,
        strict_calendar=request.strict_calendar,
        long_gap_open_sessions=request.long_gap_open_sessions,
    )
    if rebuilt != request:
        raise DatasetValidationError(
            "DatasetQualityRequest must be built via build_dataset_quality_request",
            code=DatasetErrorCode.INVALID_RANGE,
        )
    inner = _dataset_request_without_calendar_filter(request.dataset)
    dataset = get_daily_bars_dataset(session, inner)
    request_calendar = _resolve_request_calendar(session, request.dataset)
    instrument_rows = _instruments_for_report(session, request.dataset, dataset.rows)
    issues: list[DatasetQualityIssue] = []
    summaries: list[InstrumentCoverageSummary] = []
    pit_versions = 0
    correction_links = 0

    for instrument, exchange in instrument_rows:
        bars = [row for row in dataset.rows if row.instrument_id == instrument.id]
        calendar, calendar_code, has_calendar = _calendar_for_instrument(
            session,
            instrument=instrument,
            request_calendar=request_calendar,
            request_calendar_code=request.dataset.calendar_code,
        )
        sessions = (
            _sessions_in_window(session, calendar, request.dataset)
            if calendar is not None
            else ()
        )
        summary, local_issues = analyze_instrument_coverage(
            instrument_id=instrument.id,
            symbol=instrument.symbol,
            exchange_code=exchange.code if exchange is not None else None,
            asset_class=instrument.asset_class,
            currency=instrument.currency,
            bars=bars,
            sessions=sessions,
            calendar_code=calendar_code,
            has_calendar=has_calendar,
            timezone_name=calendar.timezone if calendar is not None else "UTC",
            strict_calendar=request.strict_calendar,
            long_gap_open_sessions=request.long_gap_open_sessions,
        )
        summaries.append(summary)
        issues.extend(local_issues)
        versions, links, version_issues = _pit_version_diagnostics(
            session,
            instrument=instrument,
            exchange_code=summary.exchange_code,
            request=request.dataset,
        )
        pit_versions += versions
        correction_links += links
        issues.extend(version_issues)

    issues.extend(_lookahead_issues(dataset.rows, as_of=request.dataset.as_of))
    actions = get_corporate_actions_for_dataset(session, inner)
    action_rows = tuple(
        CorporateActionQualityRow(
            instrument_id=row.instrument_id,
            symbol=row.symbol,
            exchange_code=row.exchange_code,
            action_type=row.action_type,
            effective_time=row.effective_time,
            available_time=row.available_time,
            note=row.note,
        )
        for row in actions
    )
    issues.extend(_corporate_action_issues(action_rows))
    run_summaries, ingest_issues = _ingestion_diagnostics(session, dataset.rows)
    issues.extend(ingest_issues)

    issues.sort(key=issue_sort_key)
    summaries.sort(
        key=lambda row: (row.symbol, row.exchange_code or "", str(row.instrument_id))
    )
    error_count, warning_count, info_count = count_severities(issues)
    coverage = _aggregate_coverage(
        summaries,
        total_bars=len(dataset.rows),
        pit_versions_as_of=pit_versions,
        correction_links_as_of=correction_links,
    )
    stamp = generated_at if generated_at is not None else utc_now()
    if stamp.tzinfo is None:
        raise DatasetValidationError(
            "generated_at must be timezone-aware UTC",
            code=DatasetErrorCode.NAIVE_TIMESTAMP,
        )
    return DatasetQualityReport(
        request=request,
        generated_at=stamp.astimezone(UTC),
        as_of=request.dataset.as_of,
        start_time=request.dataset.start_time,
        end_time=request.dataset.end_time,
        total_rows=len(dataset.rows),
        instrument_count=len(summaries),
        issue_count=len(issues),
        error_count=error_count,
        warning_count=warning_count,
        info_count=info_count,
        coverage=coverage,
        instruments=tuple(summaries),
        corporate_actions=action_rows,
        ingestion_runs=run_summaries,
        issues=tuple(issues),
    )


def write_dataset_quality_json(report: DatasetQualityReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report.as_mapping(), indent=2) + "\n",
        encoding="utf-8",
    )


def analyze_instrument_coverage(
    *,
    instrument_id: UUID,
    symbol: str,
    exchange_code: str | None,
    asset_class: str,
    currency: str | None,
    bars: Sequence[DailyBarDatasetRow],
    sessions: Sequence[MarketSession],
    calendar_code: str | None,
    has_calendar: bool,
    timezone_name: str,
    strict_calendar: bool,
    long_gap_open_sessions: int,
) -> tuple[InstrumentCoverageSummary, list[DatasetQualityIssue]]:
    """Coverage and calendar issues for one instrument. No database access."""
    issues: list[DatasetQualityIssue] = []
    sources = tuple(sorted({row.source_name for row in bars}))
    first = min((row.observation_time for row in bars), default=None)
    last = max((row.observation_time for row in bars), default=None)
    visible_corrections = sum(1 for row in bars if row.is_correction)

    if not has_calendar:
        issues.append(
            DatasetQualityIssue(
                severity=IssueSeverity.WARNING,
                code=QualityIssueCode.MISSING_CALENDAR,
                message=(
                    f"instrument {symbol} has no calendar; sessions were not inferred"
                ),
                instrument_id=instrument_id,
                symbol=symbol,
                exchange_code=exchange_code,
            )
        )
        summary = InstrumentCoverageSummary(
            instrument_id=instrument_id,
            symbol=symbol,
            exchange_code=exchange_code,
            asset_class=asset_class,
            currency=currency,
            calendar_code=None,
            first_observation=first,
            last_observation=last,
            bar_count=len(bars),
            source_names=sources,
            expected_open_sessions=None,
            missing_open_sessions=0,
            bars_on_closed_sessions=0,
            bars_on_unknown_sessions=0,
            coverage_ratio=None,
            visible_corrections=visible_corrections,
            has_calendar=False,
        )
        issues.extend(
            _multi_source_issues(
                bars,
                timezone_name=timezone_name,
                instrument_id=instrument_id,
                symbol=symbol,
                exchange_code=exchange_code,
            )
        )
        return summary, issues

    session_by_date = {item.session_date: item for item in sessions}
    open_dates = sorted(item.session_date for item in sessions if item.is_open)
    if not sessions:
        issues.append(
            DatasetQualityIssue(
                severity=IssueSeverity.WARNING,
                code=QualityIssueCode.NO_SESSIONS_IN_RANGE,
                message=(
                    f"calendar {calendar_code!r} has no session rows in the "
                    "requested window"
                ),
                instrument_id=instrument_id,
                symbol=symbol,
                exchange_code=exchange_code,
                metadata={"calendar_code": calendar_code or ""},
            )
        )

    bars_by_date: dict[date, list[DailyBarDatasetRow]] = defaultdict(list)
    closed = 0
    unknown = 0
    for row in bars:
        civil = session_date_for_observation(row.observation_time, timezone_name)
        bars_by_date[civil].append(row)
        market_session = session_by_date.get(civil)
        if market_session is None:
            unknown += 1
            severity = IssueSeverity.ERROR if strict_calendar else IssueSeverity.WARNING
            issues.append(
                DatasetQualityIssue(
                    severity=severity,
                    code=QualityIssueCode.BAR_ON_UNKNOWN_SESSION,
                    message=(
                        f"bar on {civil.isoformat()} has no session row in "
                        f"calendar {calendar_code!r}"
                    ),
                    instrument_id=instrument_id,
                    symbol=symbol,
                    exchange_code=exchange_code,
                    observation_time=row.observation_time,
                    source_name=row.source_name,
                    metadata={"calendar_code": calendar_code or ""},
                )
            )
            continue
        if market_session.session_kind == SessionKind.HOLIDAY:
            closed += 1
            issues.append(
                DatasetQualityIssue(
                    severity=IssueSeverity.ERROR,
                    code=QualityIssueCode.BAR_ON_HOLIDAY,
                    message=f"bar on holiday {civil.isoformat()}",
                    instrument_id=instrument_id,
                    symbol=symbol,
                    exchange_code=exchange_code,
                    observation_time=row.observation_time,
                    source_name=row.source_name,
                )
            )
        elif market_session.session_kind == SessionKind.EXCEPTIONAL_CLOSE:
            closed += 1
            issues.append(
                DatasetQualityIssue(
                    severity=IssueSeverity.ERROR,
                    code=QualityIssueCode.BAR_ON_EXCEPTIONAL_CLOSE,
                    message=f"bar on exceptional close {civil.isoformat()}",
                    instrument_id=instrument_id,
                    symbol=symbol,
                    exchange_code=exchange_code,
                    observation_time=row.observation_time,
                    source_name=row.source_name,
                )
            )

    missing_dates = [day for day in open_dates if day not in bars_by_date]
    for day in missing_dates:
        issues.append(
            DatasetQualityIssue(
                severity=IssueSeverity.WARNING,
                code=QualityIssueCode.OPEN_SESSION_WITHOUT_BAR,
                message=f"open session {day.isoformat()} has no bar",
                instrument_id=instrument_id,
                symbol=symbol,
                exchange_code=exchange_code,
                observation_time=_noon_utc(day),
                metadata={"session_date": day.isoformat()},
            )
        )
    for streak in _missing_open_streaks(open_dates, set(bars_by_date)):
        if len(streak) >= long_gap_open_sessions:
            issues.append(
                DatasetQualityIssue(
                    severity=IssueSeverity.WARNING,
                    code=QualityIssueCode.LONG_GAP,
                    message=(
                        f"long gap of {len(streak)} open sessions without bars "
                        f"from {streak[0].isoformat()} to {streak[-1].isoformat()}"
                    ),
                    instrument_id=instrument_id,
                    symbol=symbol,
                    exchange_code=exchange_code,
                    observation_time=_noon_utc(streak[0]),
                    metadata={
                        "session_dates": [item.isoformat() for item in streak],
                        "length": len(streak),
                    },
                )
            )

    covered = len(open_dates) - len(missing_dates)
    ratio = _coverage_ratio(covered, len(open_dates))
    issues.extend(
        _multi_source_issues(
            bars,
            timezone_name=timezone_name,
            instrument_id=instrument_id,
            symbol=symbol,
            exchange_code=exchange_code,
        )
    )
    summary = InstrumentCoverageSummary(
        instrument_id=instrument_id,
        symbol=symbol,
        exchange_code=exchange_code,
        asset_class=asset_class,
        currency=currency,
        calendar_code=calendar_code,
        first_observation=first,
        last_observation=last,
        bar_count=len(bars),
        source_names=sources,
        expected_open_sessions=len(open_dates),
        missing_open_sessions=len(missing_dates),
        bars_on_closed_sessions=closed,
        bars_on_unknown_sessions=unknown,
        coverage_ratio=ratio,
        visible_corrections=visible_corrections,
        has_calendar=True,
    )
    return summary, issues


def _missing_open_streaks(
    expected_open: Sequence[date], present: set[date]
) -> list[list[date]]:
    streaks: list[list[date]] = []
    current: list[date] = []
    for day in expected_open:
        if day not in present:
            current.append(day)
            continue
        if current:
            streaks.append(current)
            current = []
    if current:
        streaks.append(current)
    return streaks


def _coverage_ratio(covered: int, expected: int) -> Decimal | None:
    if expected <= 0:
        return None
    ratio = Decimal(covered) / Decimal(expected)
    return ratio.quantize(_COVERAGE_QUANTUM, rounding=ROUND_HALF_UP)


def _noon_utc(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, 12, 0, tzinfo=UTC)


def _dataset_request_without_calendar_filter(
    request: DailyBarsDatasetRequest,
) -> DailyBarsDatasetRequest:
    return build_daily_bars_dataset_request(
        as_of=request.as_of,
        start_time=request.start_time,
        end_time=request.end_time,
        symbols=request.symbols,
        instrument_ids=request.instrument_ids,
        exchange_codes=request.exchange_codes,
        asset_classes=request.asset_classes,
        currency=request.currency,
        calendar_code=None,
        require_open_session=False,
        allow_unfiltered=request.allow_unfiltered,
    )


def _resolve_request_calendar(
    session: Session, request: DailyBarsDatasetRequest
) -> MarketCalendar | None:
    if request.calendar_code is None:
        return None
    calendar = get_market_calendar_by_code(session, code=request.calendar_code)
    if calendar is None:
        raise DatasetValidationError(
            f"unknown calendar {request.calendar_code!r}",
            code=DatasetErrorCode.UNKNOWN_CALENDAR,
        )
    return calendar


def _instruments_for_report(
    session: Session,
    request: DailyBarsDatasetRequest,
    rows: Sequence[DailyBarDatasetRow],
) -> list[tuple[Instrument, Exchange | None]]:
    has_identity = any(
        (
            request.symbols is not None,
            request.instrument_ids is not None,
            request.exchange_codes is not None,
            request.asset_classes is not None,
            request.currency is not None,
        )
    )
    if has_identity:
        return list(list_instruments_for_dataset(session, request))
    seen = {row.instrument_id for row in rows}
    if not seen:
        return []
    stmt = (
        select(Instrument, Exchange)
        .outerjoin(Exchange, Instrument.exchange_id == Exchange.id)
        .where(Instrument.id.in_(seen))
        .order_by(Instrument.symbol, Instrument.asset_class, Instrument.id)
    )
    return list(session.execute(stmt).tuples().all())


def _calendar_for_instrument(
    session: Session,
    *,
    instrument: Instrument,
    request_calendar: MarketCalendar | None,
    request_calendar_code: str | None,
) -> tuple[MarketCalendar | None, str | None, bool]:
    if request_calendar is not None:
        return request_calendar, request_calendar_code, True
    if instrument.calendar_id is None:
        return None, None, False
    calendar = session.get(MarketCalendar, instrument.calendar_id)
    if calendar is None:
        return None, None, False
    return calendar, calendar.code, True


def _sessions_in_window(
    session: Session,
    calendar: MarketCalendar,
    request: DailyBarsDatasetRequest,
) -> tuple[MarketSession, ...]:
    start_day = session_date_for_observation(request.start_time, calendar.timezone)
    end_day = session_date_for_observation(request.end_time, calendar.timezone)
    rows = [
        item
        for item in list_market_sessions(session, calendar_id=calendar.id)
        if start_day <= item.session_date <= end_day
    ]
    return tuple(rows)


def _multi_source_issues(
    bars: Sequence[DailyBarDatasetRow],
    *,
    timezone_name: str,
    instrument_id: UUID,
    symbol: str,
    exchange_code: str | None,
) -> list[DatasetQualityIssue]:
    by_day: dict[date, set[str]] = defaultdict(set)
    sample: dict[date, datetime] = {}
    for row in bars:
        civil = session_date_for_observation(row.observation_time, timezone_name)
        by_day[civil].add(row.source_name)
        sample.setdefault(civil, row.observation_time)
    issues: list[DatasetQualityIssue] = []
    for day, names in sorted(by_day.items()):
        if len(names) < 2:
            continue
        issues.append(
            DatasetQualityIssue(
                severity=IssueSeverity.INFO,
                code=QualityIssueCode.MULTIPLE_SOURCES_SAME_DAY,
                message=(
                    f"{len(names)} sources on {day.isoformat()}: "
                    + ", ".join(sorted(names))
                ),
                instrument_id=instrument_id,
                symbol=symbol,
                exchange_code=exchange_code,
                observation_time=sample[day],
                metadata={"sources": sorted(names), "session_date": day.isoformat()},
            )
        )
    return issues


def _lookahead_issues(
    bars: Sequence[DailyBarDatasetRow], *, as_of: datetime
) -> list[DatasetQualityIssue]:
    issues: list[DatasetQualityIssue] = []
    for row in bars:
        if row.available_time <= as_of:
            continue
        issues.append(
            DatasetQualityIssue(
                severity=IssueSeverity.ERROR,
                code=QualityIssueCode.LOOKAHEAD,
                message="dataset row available_time is after as_of",
                instrument_id=row.instrument_id,
                symbol=row.symbol,
                exchange_code=row.exchange_code,
                observation_time=row.observation_time,
                source_name=row.source_name,
            )
        )
    return issues


def _pit_version_diagnostics(
    session: Session,
    *,
    instrument: Instrument,
    exchange_code: str | None,
    request: DailyBarsDatasetRequest,
) -> tuple[int, int, list[DatasetQualityIssue]]:
    stmt = (
        select(DailyBar, DataSource)
        .join(DataSource, DailyBar.source_id == DataSource.id)
        .where(DailyBar.instrument_id == instrument.id)
        .where(DailyBar.available_time <= request.as_of)
        .where(DailyBar.observation_time >= request.start_time)
        .where(DailyBar.observation_time <= request.end_time)
        .order_by(
            DailyBar.observation_time,
            DataSource.name,
            DailyBar.available_time,
        )
    )
    versions = list(session.execute(stmt).tuples().all())
    grouped: dict[tuple[UUID, datetime], list[DailyBar]] = defaultdict(list)
    links = 0
    issues: list[DatasetQualityIssue] = []
    source_by_bar_id = {bar.id: source.name for bar, source in versions}
    for bar, source in versions:
        grouped[(bar.source_id, bar.observation_time)].append(bar)
        if bar.supersedes_daily_bar_id is not None:
            links += 1
            issues.append(
                DatasetQualityIssue(
                    severity=IssueSeverity.INFO,
                    code=QualityIssueCode.CORRECTION_VISIBLE,
                    message="correction visible at as_of",
                    instrument_id=instrument.id,
                    symbol=instrument.symbol,
                    exchange_code=exchange_code,
                    observation_time=bar.observation_time,
                    source_name=source.name,
                    metadata={
                        "supersedes_daily_bar_id": str(bar.supersedes_daily_bar_id),
                        "available_time": bar.available_time.isoformat(),
                        "correction_reason": bar.correction_reason or "",
                    },
                )
            )
    for (_source_id, observation_time), group in grouped.items():
        if len(group) < 2:
            continue
        issues.append(
            DatasetQualityIssue(
                severity=IssueSeverity.INFO,
                code=QualityIssueCode.MULTIPLE_VERSIONS_AS_OF,
                message=(
                    f"{len(group)} PIT versions available as of "
                    f"{request.as_of.isoformat()}"
                ),
                instrument_id=instrument.id,
                symbol=instrument.symbol,
                exchange_code=exchange_code,
                observation_time=observation_time,
                source_name=source_by_bar_id[group[0].id],
                metadata={"version_count": len(group)},
            )
        )
    return len(versions), links, issues


def _corporate_action_issues(
    rows: Sequence[CorporateActionQualityRow],
) -> list[DatasetQualityIssue]:
    issues: list[DatasetQualityIssue] = []
    for row in rows:
        issues.append(
            DatasetQualityIssue(
                severity=IssueSeverity.INFO,
                code=QualityIssueCode.CORPORATE_ACTION_VISIBLE,
                message=(
                    f"{row.action_type} visible (effective "
                    f"{row.effective_time.isoformat()}); not applied to OHLCV"
                ),
                instrument_id=row.instrument_id,
                symbol=row.symbol,
                exchange_code=row.exchange_code,
                observation_time=row.effective_time,
                metadata={
                    "action_type": row.action_type,
                    "available_time": row.available_time.isoformat(),
                },
            )
        )
    return issues


def _ingestion_diagnostics(
    session: Session, bars: Sequence[DailyBarDatasetRow]
) -> tuple[tuple[IngestionRunSummary, ...], list[DatasetQualityIssue]]:
    run_ids = tuple(dict.fromkeys(row.ingestion_run_id for row in bars))
    if not run_ids:
        return (), []
    stmt = (
        select(IngestionRun, DataSource)
        .join(DataSource, IngestionRun.source_id == DataSource.id)
        .where(IngestionRun.id.in_(run_ids))
        .order_by(DataSource.name, IngestionRun.started_at, IngestionRun.id)
    )
    issues: list[DatasetQualityIssue] = []
    summaries: list[IngestionRunSummary] = []
    for run, source in session.execute(stmt).tuples():
        errors = list_ingestion_errors(session, ingestion_run_id=run.id)
        summaries.append(
            IngestionRunSummary(
                ingestion_run_id=run.id,
                source_name=source.name,
                status=run.status,
                accepted_count=run.accepted_count,
                rejected_count=run.rejected_count,
                started_at=run.started_at,
                error_count=len(errors),
            )
        )
        if run.rejected_count > 0:
            issues.append(
                DatasetQualityIssue(
                    severity=IssueSeverity.WARNING,
                    code=QualityIssueCode.INGESTION_REJECTIONS,
                    message=(
                        f"ingestion run rejected {run.rejected_count} row(s) "
                        f"(accepted {run.accepted_count})"
                    ),
                    source_name=source.name,
                    metadata={
                        "ingestion_run_id": str(run.id),
                        "accepted_count": run.accepted_count,
                        "rejected_count": run.rejected_count,
                    },
                )
            )
        for error in errors:
            issues.append(
                DatasetQualityIssue(
                    severity=IssueSeverity.WARNING,
                    code=QualityIssueCode.INGESTION_ERROR,
                    message=error.error_message,
                    source_name=source.name,
                    metadata={
                        "ingestion_run_id": str(run.id),
                        "error_code": error.error_code,
                        "record_index": error.record_index,
                    },
                )
            )
    return tuple(summaries), issues


def _aggregate_coverage(
    summaries: Sequence[InstrumentCoverageSummary],
    *,
    total_bars: int,
    pit_versions_as_of: int,
    correction_links_as_of: int,
) -> DatasetCoverageSummary:
    sources = tuple(sorted({name for row in summaries for name in row.source_names}))
    firsts = [row.first_observation for row in summaries if row.first_observation]
    lasts = [row.last_observation for row in summaries if row.last_observation]
    expected_parts = [
        row.expected_open_sessions
        for row in summaries
        if row.expected_open_sessions is not None
    ]
    expected = sum(expected_parts) if expected_parts else None
    missing = sum(row.missing_open_sessions for row in summaries)
    outside = sum(
        row.bars_on_closed_sessions + row.bars_on_unknown_sessions for row in summaries
    )
    ratio = None
    if expected is not None:
        ratio = _coverage_ratio(expected - missing, expected)
    return DatasetCoverageSummary(
        instrument_count=len(summaries),
        total_bars=total_bars,
        source_names=sources,
        first_observation=min(firsts) if firsts else None,
        last_observation=max(lasts) if lasts else None,
        expected_open_sessions=expected,
        missing_open_sessions=missing,
        bars_outside_calendar=outside,
        coverage_ratio=ratio,
        visible_corrections=sum(row.visible_corrections for row in summaries),
        pit_versions_as_of=pit_versions_as_of,
        correction_links_as_of=correction_links_as_of,
    )
