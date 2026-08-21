"""PostgreSQL dataset quality reports."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from quant_platform.data.models import IngestionStatus, Instrument
from quant_platform.data.repository import (
    create_calendar,
    create_corporate_action,
    create_exchange,
    create_ingestion_run,
    create_session,
    finish_ingestion_run,
    get_daily_bars,
    insert_daily_bar_correction,
    insert_daily_bars,
    insert_ingestion_error,
    upsert_data_source,
    upsert_instrument,
)
from quant_platform.data.validation import DailyBarDraft, IngestionErrorCode
from quant_platform.research.quality import get_dataset_quality_report
from quant_platform.research.quality_types import (
    QualityIssueCode,
    build_dataset_quality_request,
    issue_sort_key,
)

pytestmark = pytest.mark.postgres


def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:8]}"


def _draft(
    symbol: str,
    *,
    day: int,
    available_day: int,
    close: str,
) -> DailyBarDraft:
    price = Decimal(close)
    return DailyBarDraft(
        symbol=symbol,
        observation_time=datetime(2024, 1, day, tzinfo=UTC),
        available_time=datetime(2024, 1, available_day, tzinfo=UTC),
        open=price,
        high=price + Decimal("1"),
        low=price - Decimal("1") if price >= 1 else Decimal("0"),
        close=price,
        volume=Decimal("100"),
    )


def _insert_bar(
    session: Session,
    *,
    instrument: Instrument,
    source_id: UUID,
    ingestion_run_id: UUID,
    day: int,
    available_day: int,
    close: str,
) -> None:
    insert_daily_bars(
        session,
        drafts=[
            _draft(instrument.symbol, day=day, available_day=available_day, close=close)
        ],
        instruments_by_symbol={instrument.symbol: instrument},
        source_id=source_id,
        ingestion_run_id=ingestion_run_id,
    )


def _window(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "as_of": datetime(2024, 1, 10, tzinfo=UTC),
        "start_time": datetime(2024, 1, 1, tzinfo=UTC),
        "end_time": datetime(2024, 1, 5, tzinfo=UTC),
    }
    values.update(overrides)
    return values


def test_quality_report_clean_open_session(db_session: Session) -> None:
    source = upsert_data_source(db_session, name=_unique("src"), vendor="local_csv")
    calendar = create_calendar(
        db_session, code=_unique("cal"), name="Test", timezone="UTC"
    )
    create_session(
        db_session,
        calendar_id=calendar.id,
        session_date=date(2024, 1, 2),
        session_kind="open",
    )
    create_session(
        db_session,
        calendar_id=calendar.id,
        session_date=date(2024, 1, 1),
        session_kind="holiday",
    )
    instrument = upsert_instrument(
        db_session,
        symbol=_unique("OK"),
        asset_class="equity",
        calendar_id=calendar.id,
    )
    run = create_ingestion_run(db_session, source_id=source.id)
    _insert_bar(
        db_session,
        instrument=instrument,
        source_id=source.id,
        ingestion_run_id=run.id,
        day=2,
        available_day=3,
        close="10",
    )
    report = get_dataset_quality_report(
        db_session,
        build_dataset_quality_request(
            **_window(),
            symbols=[instrument.symbol],
            calendar_code=calendar.code,
        ),
        generated_at=datetime(2024, 1, 10, tzinfo=UTC),
    )
    assert report.total_rows == 1
    assert report.error_count == 0
    assert report.warning_count == 0
    assert report.instruments[0].coverage_ratio == Decimal("1.0000")
    assert report.instruments[0].missing_open_sessions == 0


def test_quality_report_missing_calendar_warning(db_session: Session) -> None:
    source = upsert_data_source(db_session, name=_unique("src"), vendor="local_csv")
    instrument = upsert_instrument(
        db_session, symbol=_unique("NCAL"), asset_class="equity"
    )
    run = create_ingestion_run(db_session, source_id=source.id)
    _insert_bar(
        db_session,
        instrument=instrument,
        source_id=source.id,
        ingestion_run_id=run.id,
        day=2,
        available_day=3,
        close="10",
    )
    report = get_dataset_quality_report(
        db_session,
        build_dataset_quality_request(**_window(), symbols=[instrument.symbol]),
        generated_at=datetime(2024, 1, 10, tzinfo=UTC),
    )
    assert report.total_rows == 1
    assert report.error_count == 0
    assert any(item.code == QualityIssueCode.MISSING_CALENDAR for item in report.issues)
    assert report.instruments[0].has_calendar is False


def test_quality_report_calendar_gaps_and_closed_bars(db_session: Session) -> None:
    source = upsert_data_source(db_session, name=_unique("src"), vendor="local_csv")
    venue = create_exchange(db_session, code=_unique("XNYS"), timezone="UTC")
    calendar = create_calendar(
        db_session, code=_unique("cal"), name="Test", timezone="UTC"
    )
    create_session(
        db_session,
        calendar_id=calendar.id,
        session_date=date(2024, 1, 1),
        session_kind="holiday",
    )
    create_session(
        db_session,
        calendar_id=calendar.id,
        session_date=date(2024, 1, 2),
        session_kind="open",
    )
    create_session(
        db_session,
        calendar_id=calendar.id,
        session_date=date(2024, 1, 3),
        session_kind="open",
    )
    create_session(
        db_session,
        calendar_id=calendar.id,
        session_date=date(2024, 1, 4),
        session_kind="exceptional_close",
    )
    instrument = upsert_instrument(
        db_session,
        symbol=_unique("CAL"),
        asset_class="equity",
        exchange_id=venue.id,
        calendar_id=calendar.id,
    )
    run = create_ingestion_run(db_session, source_id=source.id)
    _insert_bar(
        db_session,
        instrument=instrument,
        source_id=source.id,
        ingestion_run_id=run.id,
        day=1,
        available_day=2,
        close="10",
    )
    _insert_bar(
        db_session,
        instrument=instrument,
        source_id=source.id,
        ingestion_run_id=run.id,
        day=2,
        available_day=3,
        close="11",
    )
    _insert_bar(
        db_session,
        instrument=instrument,
        source_id=source.id,
        ingestion_run_id=run.id,
        day=4,
        available_day=5,
        close="12",
    )
    request = build_dataset_quality_request(
        **_window(),
        symbols=[instrument.symbol],
        calendar_code=calendar.code,
    )
    report = get_dataset_quality_report(
        db_session,
        request,
        generated_at=datetime(2024, 1, 10, tzinfo=UTC),
    )
    codes = [item.code for item in report.issues]
    assert QualityIssueCode.BAR_ON_HOLIDAY in codes
    assert QualityIssueCode.BAR_ON_EXCEPTIONAL_CLOSE in codes
    assert QualityIssueCode.OPEN_SESSION_WITHOUT_BAR in codes
    assert report.error_count >= 2
    assert report.coverage.missing_open_sessions == 1
    again = get_dataset_quality_report(
        db_session,
        request,
        generated_at=datetime(2024, 1, 10, tzinfo=UTC),
    )
    assert [item.as_mapping() for item in again.issues] == [
        item.as_mapping() for item in report.issues
    ]
    assert list(report.issues) == sorted(report.issues, key=issue_sort_key)


def test_quality_report_pit_corrections_hide_future(db_session: Session) -> None:
    source = upsert_data_source(db_session, name=_unique("src"), vendor="local_csv")
    instrument = upsert_instrument(
        db_session, symbol=_unique("COR"), asset_class="equity"
    )
    run = create_ingestion_run(db_session, source_id=source.id)
    _insert_bar(
        db_session,
        instrument=instrument,
        source_id=source.id,
        ingestion_run_id=run.id,
        day=1,
        available_day=2,
        close="10",
    )
    original = get_daily_bars(db_session, instrument_id=instrument.id)[0]
    insert_daily_bar_correction(
        db_session,
        superseded=original,
        available_time=datetime(2024, 1, 8, tzinfo=UTC),
        open=Decimal("10"),
        high=Decimal("12"),
        low=Decimal("9"),
        close=Decimal("11"),
        volume=Decimal("100"),
        ingestion_run_id=run.id,
        reason="restated close",
    )
    early = get_dataset_quality_report(
        db_session,
        build_dataset_quality_request(
            as_of=datetime(2024, 1, 3, tzinfo=UTC),
            start_time=datetime(2024, 1, 1, tzinfo=UTC),
            end_time=datetime(2024, 1, 5, tzinfo=UTC),
            symbols=[instrument.symbol],
        ),
        generated_at=datetime(2024, 1, 10, tzinfo=UTC),
    )
    assert early.coverage.visible_corrections == 0
    assert all(
        item.code != QualityIssueCode.CORRECTION_VISIBLE for item in early.issues
    )
    late = get_dataset_quality_report(
        db_session,
        build_dataset_quality_request(
            as_of=datetime(2024, 1, 10, tzinfo=UTC),
            start_time=datetime(2024, 1, 1, tzinfo=UTC),
            end_time=datetime(2024, 1, 5, tzinfo=UTC),
            symbols=[instrument.symbol],
        ),
        generated_at=datetime(2024, 1, 10, tzinfo=UTC),
    )
    assert late.coverage.visible_corrections == 1
    assert any(item.code == QualityIssueCode.CORRECTION_VISIBLE for item in late.issues)
    assert any(
        item.code == QualityIssueCode.MULTIPLE_VERSIONS_AS_OF for item in late.issues
    )


def test_quality_report_corporate_actions_and_ingestion_errors(
    db_session: Session,
) -> None:
    source = upsert_data_source(db_session, name=_unique("src"), vendor="local_csv")
    venue = create_exchange(db_session, code=_unique("XNYS"), timezone="UTC")
    instrument = upsert_instrument(
        db_session,
        symbol=_unique("FICT"),
        asset_class="equity",
        exchange_id=venue.id,
        currency="USD",
    )
    run = create_ingestion_run(db_session, source_id=source.id)
    _insert_bar(
        db_session,
        instrument=instrument,
        source_id=source.id,
        ingestion_run_id=run.id,
        day=2,
        available_day=3,
        close="40",
    )
    insert_ingestion_error(
        db_session,
        ingestion_run_id=run.id,
        source_id=source.id,
        error_code=IngestionErrorCode.INVALID_OHLC,
        error_message="bad row",
        record_index=1,
    )
    finish_ingestion_run(
        db_session,
        run,
        status=IngestionStatus.SUCCEEDED,
        row_count=2,
        accepted_count=1,
        rejected_count=1,
    )
    create_corporate_action(
        db_session,
        instrument_id=instrument.id,
        action_type="split",
        effective_time=datetime(2024, 1, 2, tzinfo=UTC),
        available_time=datetime(2023, 12, 15, tzinfo=UTC),
        quantity_before=Decimal("1"),
        quantity_after=Decimal("4"),
        note="fictional",
    )
    report = get_dataset_quality_report(
        db_session,
        build_dataset_quality_request(**_window(), symbols=[instrument.symbol]),
        generated_at=datetime(2024, 1, 10, tzinfo=UTC),
    )
    assert len(report.corporate_actions) == 1
    assert report.corporate_actions[0].action_type == "split"
    assert report.instruments[0].bar_count == 1
    codes = {item.code for item in report.issues}
    assert QualityIssueCode.CORPORATE_ACTION_VISIBLE in codes
    assert QualityIssueCode.INGESTION_ERROR in codes
    assert QualityIssueCode.INGESTION_REJECTIONS in codes
    assert report.ingestion_runs[0].rejected_count == 1
    assert list(report.issues) == sorted(report.issues, key=issue_sort_key)
