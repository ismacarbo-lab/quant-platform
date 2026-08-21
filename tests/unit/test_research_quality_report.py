"""Dataset quality request validation and coverage analysis without a database."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from quant_platform.data.models import MarketSession, SessionKind
from quant_platform.research.errors import DatasetErrorCode, DatasetValidationError
from quant_platform.research.quality import (
    _missing_open_streaks,
    analyze_instrument_coverage,
    write_dataset_quality_json,
)
from quant_platform.research.quality_types import (
    ISSUE_MAPPING_COLUMNS,
    DatasetCoverageSummary,
    DatasetQualityIssue,
    DatasetQualityReport,
    DatasetQualityRequest,
    InstrumentCoverageSummary,
    IssueSeverity,
    QualityIssueCode,
    build_dataset_quality_request,
    count_severities,
)
from quant_platform.research.types import DailyBarDatasetRow, DailyBarsDatasetRequest


def _request_kwargs(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "as_of": datetime(2024, 1, 10, tzinfo=UTC),
        "start_time": datetime(2024, 1, 1, tzinfo=UTC),
        "end_time": datetime(2024, 1, 5, tzinfo=UTC),
        "symbols": ["FICT"],
    }
    base.update(overrides)
    return base


def _bar(**overrides: object) -> DailyBarDatasetRow:
    values: dict[str, object] = {
        "instrument_id": uuid4(),
        "symbol": "FICT",
        "exchange_code": "XNYS",
        "asset_class": "equity",
        "currency": "USD",
        "observation_time": datetime(2024, 1, 2, tzinfo=UTC),
        "available_time": datetime(2024, 1, 3, tzinfo=UTC),
        "open": Decimal("10"),
        "high": Decimal("11"),
        "low": Decimal("9"),
        "close": Decimal("10"),
        "volume": None,
        "source_name": "local_csv",
        "ingestion_run_id": uuid4(),
        "is_correction": False,
        "correction_reason": None,
    }
    values.update(overrides)
    return DailyBarDatasetRow(**values)  # type: ignore[arg-type]


def _session(day: date, kind: str) -> MarketSession:
    is_open = kind in {SessionKind.OPEN.value, SessionKind.HALF_SESSION.value}
    return MarketSession(
        calendar_id=uuid4(),
        session_date=day,
        session_kind=kind,
        is_open=is_open,
    )


def test_quality_request_requires_as_of() -> None:
    with pytest.raises(DatasetValidationError, match="as_of is required") as exc:
        build_dataset_quality_request(
            start_time=datetime(2024, 1, 1, tzinfo=UTC),
            end_time=datetime(2024, 1, 5, tzinfo=UTC),
            symbols=["FICT"],
        )
    assert exc.value.code == DatasetErrorCode.MISSING_AS_OF


def test_quality_request_rejects_naive_timestamps() -> None:
    with pytest.raises(DatasetValidationError, match="timezone-aware") as exc:
        build_dataset_quality_request(**_request_kwargs(as_of=datetime(2024, 1, 10)))
    assert exc.value.code == DatasetErrorCode.NAIVE_TIMESTAMP


def test_quality_request_rejects_invalid_gap_threshold() -> None:
    with pytest.raises(DatasetValidationError, match="long_gap_open_sessions") as exc:
        build_dataset_quality_request(**_request_kwargs(long_gap_open_sessions=0))
    assert exc.value.code == DatasetErrorCode.INVALID_RANGE


def test_issue_mapping_columns_are_stable() -> None:
    issue = DatasetQualityIssue(
        severity=IssueSeverity.ERROR,
        code=QualityIssueCode.BAR_ON_HOLIDAY,
        message="bar on holiday",
        symbol="FICT",
    )
    assert tuple(issue.as_mapping()) == ISSUE_MAPPING_COLUMNS
    assert issue.as_mapping()["severity"] == "error"


def test_severity_counts() -> None:
    issues = (
        DatasetQualityIssue(severity=IssueSeverity.ERROR, code="a", message="e"),
        DatasetQualityIssue(severity=IssueSeverity.WARNING, code="b", message="w"),
        DatasetQualityIssue(severity=IssueSeverity.WARNING, code="c", message="w2"),
        DatasetQualityIssue(severity=IssueSeverity.INFO, code="d", message="i"),
    )
    assert count_severities(issues) == (1, 2, 1)


def test_missing_calendar_warning() -> None:
    instrument_id = uuid4()
    summary, issues = analyze_instrument_coverage(
        instrument_id=instrument_id,
        symbol="FICT",
        exchange_code="XNYS",
        asset_class="equity",
        currency="USD",
        bars=[_bar(instrument_id=instrument_id)],
        sessions=(),
        calendar_code=None,
        has_calendar=False,
        timezone_name="UTC",
        strict_calendar=False,
        long_gap_open_sessions=5,
    )
    assert summary.has_calendar is False
    assert summary.coverage_ratio is None
    assert [item.code for item in issues] == [QualityIssueCode.MISSING_CALENDAR]


def test_open_session_without_bar_and_holiday_bar() -> None:
    instrument_id = uuid4()
    holiday_bar = _bar(
        instrument_id=instrument_id,
        observation_time=datetime(2024, 1, 1, tzinfo=UTC),
        available_time=datetime(2024, 1, 2, tzinfo=UTC),
    )
    open_bar = _bar(
        instrument_id=instrument_id,
        observation_time=datetime(2024, 1, 2, tzinfo=UTC),
        available_time=datetime(2024, 1, 3, tzinfo=UTC),
    )
    sessions = (
        _session(date(2024, 1, 1), SessionKind.HOLIDAY.value),
        _session(date(2024, 1, 2), SessionKind.OPEN.value),
        _session(date(2024, 1, 3), SessionKind.OPEN.value),
        _session(date(2024, 1, 4), SessionKind.HALF_SESSION.value),
    )
    summary, issues = analyze_instrument_coverage(
        instrument_id=instrument_id,
        symbol="FICT",
        exchange_code="XNYS",
        asset_class="equity",
        currency="USD",
        bars=[holiday_bar, open_bar],
        sessions=sessions,
        calendar_code="TEST",
        has_calendar=True,
        timezone_name="UTC",
        strict_calendar=False,
        long_gap_open_sessions=5,
    )
    codes = [item.code for item in issues]
    assert QualityIssueCode.BAR_ON_HOLIDAY in codes
    assert codes.count(QualityIssueCode.OPEN_SESSION_WITHOUT_BAR) == 2
    assert summary.expected_open_sessions == 3
    assert summary.missing_open_sessions == 2
    assert summary.bars_on_closed_sessions == 1
    assert summary.coverage_ratio == Decimal("0.3333")


def test_exceptional_close_and_strict_unknown_session() -> None:
    instrument_id = uuid4()
    closed_bar = _bar(
        instrument_id=instrument_id,
        observation_time=datetime(2024, 1, 1, tzinfo=UTC),
    )
    unknown_bar = _bar(
        instrument_id=instrument_id,
        observation_time=datetime(2024, 1, 2, tzinfo=UTC),
        available_time=datetime(2024, 1, 3, tzinfo=UTC),
    )
    sessions = (_session(date(2024, 1, 1), SessionKind.EXCEPTIONAL_CLOSE.value),)
    _summary, issues = analyze_instrument_coverage(
        instrument_id=instrument_id,
        symbol="FICT",
        exchange_code=None,
        asset_class="equity",
        currency=None,
        bars=[closed_bar, unknown_bar],
        sessions=sessions,
        calendar_code="TEST",
        has_calendar=True,
        timezone_name="UTC",
        strict_calendar=True,
        long_gap_open_sessions=5,
    )
    by_code = {item.code: item for item in issues}
    assert by_code[QualityIssueCode.BAR_ON_EXCEPTIONAL_CLOSE].severity == "error"
    assert by_code[QualityIssueCode.BAR_ON_UNKNOWN_SESSION].severity == "error"


def test_long_gap_streak_helper() -> None:
    expected = [date(2024, 1, day) for day in (2, 3, 4, 5, 8)]
    present = {date(2024, 1, 2), date(2024, 1, 8)}
    streaks = _missing_open_streaks(expected, present)
    assert streaks == [
        [date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 5)],
    ]


def test_report_json_serialization(tmp_path) -> None:
    generated = datetime(2024, 1, 10, tzinfo=UTC)
    dataset = DailyBarsDatasetRequest(
        as_of=generated,
        start_time=datetime(2024, 1, 1, tzinfo=UTC),
        end_time=datetime(2024, 1, 5, tzinfo=UTC),
        symbols=("FICT",),
    )
    request = DatasetQualityRequest(dataset=dataset)
    coverage = DatasetCoverageSummary(
        instrument_count=1,
        total_bars=1,
        source_names=("local_csv",),
        first_observation=datetime(2024, 1, 2, tzinfo=UTC),
        last_observation=datetime(2024, 1, 2, tzinfo=UTC),
        expected_open_sessions=None,
        missing_open_sessions=0,
        bars_outside_calendar=0,
        coverage_ratio=None,
        visible_corrections=0,
        pit_versions_as_of=1,
        correction_links_as_of=0,
    )
    instrument = InstrumentCoverageSummary(
        instrument_id=uuid4(),
        symbol="FICT",
        exchange_code="XNYS",
        asset_class="equity",
        currency="USD",
        calendar_code=None,
        first_observation=datetime(2024, 1, 2, tzinfo=UTC),
        last_observation=datetime(2024, 1, 2, tzinfo=UTC),
        bar_count=1,
        source_names=("local_csv",),
        expected_open_sessions=None,
        missing_open_sessions=0,
        bars_on_closed_sessions=0,
        bars_on_unknown_sessions=0,
        coverage_ratio=None,
        visible_corrections=0,
        has_calendar=False,
    )
    issue = DatasetQualityIssue(
        severity=IssueSeverity.WARNING,
        code=QualityIssueCode.MISSING_CALENDAR,
        message="no calendar",
        symbol="FICT",
        instrument_id=instrument.instrument_id,
    )
    report = DatasetQualityReport(
        request=request,
        generated_at=generated,
        as_of=dataset.as_of,
        start_time=dataset.start_time,
        end_time=dataset.end_time,
        total_rows=1,
        instrument_count=1,
        issue_count=1,
        error_count=0,
        warning_count=1,
        info_count=0,
        coverage=coverage,
        instruments=(instrument,),
        corporate_actions=(),
        ingestion_runs=(),
        issues=(issue,),
    )
    path = tmp_path / "quality.json"
    write_dataset_quality_json(report, path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["as_of"] == generated.isoformat()
    assert payload["warning_count"] == 1
    assert payload["issues"][0]["code"] == "missing_calendar"
    assert list(payload["issues"][0]) == list(ISSUE_MAPPING_COLUMNS)
    json.dumps(payload)
