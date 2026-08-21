"""PostgreSQL research dataset queries (point-in-time, calendars, corporate actions)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from quant_platform.data.models import Instrument
from quant_platform.data.repository import (
    create_calendar,
    create_corporate_action,
    create_exchange,
    create_ingestion_run,
    create_session,
    get_daily_bars,
    insert_daily_bar_correction,
    insert_daily_bars,
    upsert_data_source,
    upsert_instrument,
)
from quant_platform.data.validation import DailyBarDraft
from quant_platform.research.datasets import (
    get_corporate_actions_for_dataset,
    get_daily_bars_dataset,
)
from quant_platform.research.errors import DatasetErrorCode, DatasetValidationError
from quant_platform.research.types import build_daily_bars_dataset_request

pytestmark = pytest.mark.postgres


def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:8]}"


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


def _draft(
    symbol: str,
    *,
    day: int,
    available_day: int,
    close: str,
    high: str | None = None,
) -> DailyBarDraft:
    price = Decimal(close)
    top = Decimal(high) if high is not None else price + Decimal("1")
    return DailyBarDraft(
        symbol=symbol,
        observation_time=datetime(2024, 1, day, tzinfo=UTC),
        available_time=datetime(2024, 1, available_day, tzinfo=UTC),
        open=price,
        high=top,
        low=price - Decimal("1") if price >= 1 else Decimal("0"),
        close=price,
        volume=Decimal("100"),
    )


def test_dataset_basic_ohlcv_and_filters(db_session: Session) -> None:
    source = upsert_data_source(db_session, name=_unique("src"), vendor="local_csv")
    nyse = create_exchange(db_session, code=_unique("XNYS"), timezone="UTC")
    nasdaq = create_exchange(db_session, code=_unique("XNAS"), timezone="UTC")
    symbol = _unique("AAA")
    equity = upsert_instrument(
        db_session,
        symbol=symbol,
        asset_class="equity",
        exchange_id=nyse.id,
        currency="USD",
    )
    crypto = upsert_instrument(
        db_session,
        symbol=symbol,
        asset_class="crypto",
        exchange_id=nasdaq.id,
        currency="USD",
    )
    other = upsert_instrument(
        db_session,
        symbol=_unique("BBB"),
        asset_class="equity",
        exchange_id=nyse.id,
        currency="USD",
    )
    run = create_ingestion_run(db_session, source_id=source.id)
    _insert_bar(
        db_session,
        instrument=equity,
        source_id=source.id,
        ingestion_run_id=run.id,
        day=2,
        available_day=3,
        close="10",
    )
    _insert_bar(
        db_session,
        instrument=crypto,
        source_id=source.id,
        ingestion_run_id=run.id,
        day=2,
        available_day=3,
        close="20",
    )
    _insert_bar(
        db_session,
        instrument=other,
        source_id=source.id,
        ingestion_run_id=run.id,
        day=2,
        available_day=3,
        close="30",
    )
    by_symbol = get_daily_bars_dataset(
        db_session,
        build_daily_bars_dataset_request(
            as_of=datetime(2024, 1, 10, tzinfo=UTC),
            start_time=datetime(2024, 1, 1, tzinfo=UTC),
            end_time=datetime(2024, 1, 5, tzinfo=UTC),
            symbols=[symbol],
        ),
    )
    assert len(by_symbol) == 2
    assert {row.asset_class for row in by_symbol} == {"equity", "crypto"}
    by_exchange = get_daily_bars_dataset(
        db_session,
        build_daily_bars_dataset_request(
            as_of=datetime(2024, 1, 10, tzinfo=UTC),
            start_time=datetime(2024, 1, 1, tzinfo=UTC),
            end_time=datetime(2024, 1, 5, tzinfo=UTC),
            exchange_codes=[nyse.code],
            symbols=[symbol, other.symbol],
        ),
    )
    assert {row.symbol for row in by_exchange} == {symbol, other.symbol}
    assert {row.exchange_code for row in by_exchange} == {nyse.code}
    by_class = get_daily_bars_dataset(
        db_session,
        build_daily_bars_dataset_request(
            as_of=datetime(2024, 1, 10, tzinfo=UTC),
            start_time=datetime(2024, 1, 1, tzinfo=UTC),
            end_time=datetime(2024, 1, 5, tzinfo=UTC),
            symbols=[symbol],
            asset_classes=["equity"],
        ),
    )
    assert len(by_class) == 1
    assert by_class.rows[0].instrument_id == equity.id
    assert by_class.rows[0].source_name == source.name
    assert list(by_class.rows) == sorted(
        by_class.rows,
        key=lambda row: (row.symbol, row.exchange_code or "", row.observation_time),
    )


def test_dataset_pit_corrections_and_no_future(db_session: Session) -> None:
    source = upsert_data_source(db_session, name=_unique("src"), vendor="local_csv")
    venue = create_exchange(db_session, code=_unique("XNYS"), timezone="UTC")
    instrument = upsert_instrument(
        db_session,
        symbol=_unique("COR"),
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
        day=1,
        available_day=2,
        close="10",
    )
    stored = get_daily_bars(db_session, instrument_id=instrument.id)[0]
    insert_daily_bar_correction(
        db_session,
        superseded=stored,
        available_time=datetime(2024, 1, 5, tzinfo=UTC),
        open=Decimal("10"),
        high=Decimal("12"),
        low=Decimal("9"),
        close=Decimal("11"),
        volume=Decimal("100"),
        ingestion_run_id=run.id,
        reason="restated close",
    )
    _insert_bar(
        db_session,
        instrument=instrument,
        source_id=source.id,
        ingestion_run_id=run.id,
        day=8,
        available_day=20,
        close="50",
    )
    early = get_daily_bars_dataset(
        db_session,
        build_daily_bars_dataset_request(
            as_of=datetime(2024, 1, 3, tzinfo=UTC),
            start_time=datetime(2024, 1, 1, tzinfo=UTC),
            end_time=datetime(2024, 1, 10, tzinfo=UTC),
            symbols=[instrument.symbol],
        ),
    )
    assert len(early) == 1
    assert early.rows[0].close == Decimal("10")
    assert early.rows[0].is_correction is False
    late = get_daily_bars_dataset(
        db_session,
        build_daily_bars_dataset_request(
            as_of=datetime(2024, 1, 6, tzinfo=UTC),
            start_time=datetime(2024, 1, 1, tzinfo=UTC),
            end_time=datetime(2024, 1, 10, tzinfo=UTC),
            symbols=[instrument.symbol],
        ),
    )
    assert len(late) == 1
    assert late.rows[0].close == Decimal("11")
    assert late.rows[0].is_correction is True
    assert late.rows[0].correction_reason == "restated close"
    as_of_mid_future = get_daily_bars_dataset(
        db_session,
        build_daily_bars_dataset_request(
            as_of=datetime(2024, 1, 10, tzinfo=UTC),
            start_time=datetime(2024, 1, 1, tzinfo=UTC),
            end_time=datetime(2024, 1, 10, tzinfo=UTC),
            symbols=[instrument.symbol],
        ),
    )
    assert [row.observation_time.day for row in as_of_mid_future] == [1]


def test_dataset_calendar_open_sessions(db_session: Session) -> None:
    source = upsert_data_source(db_session, name=_unique("src"), vendor="local_csv")
    venue = create_exchange(db_session, code=_unique("XNYS"), timezone="UTC")
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
        session_date=date(2024, 1, 3),
        session_kind="holiday",
    )
    create_session(
        db_session,
        calendar_id=calendar.id,
        session_date=date(2024, 1, 4),
        session_kind="half_session",
    )
    instrument = upsert_instrument(
        db_session,
        symbol=_unique("CAL"),
        asset_class="equity",
        exchange_id=venue.id,
        calendar_id=calendar.id,
    )
    run = create_ingestion_run(db_session, source_id=source.id)
    insert_daily_bars(
        db_session,
        drafts=[
            _draft(instrument.symbol, day=2, available_day=3, close="10"),
            _draft(instrument.symbol, day=3, available_day=4, close="11"),
            _draft(instrument.symbol, day=4, available_day=5, close="12"),
        ],
        instruments_by_symbol={instrument.symbol: instrument},
        source_id=source.id,
        ingestion_run_id=run.id,
    )
    dataset = get_daily_bars_dataset(
        db_session,
        build_daily_bars_dataset_request(
            as_of=datetime(2024, 1, 10, tzinfo=UTC),
            start_time=datetime(2024, 1, 1, tzinfo=UTC),
            end_time=datetime(2024, 1, 5, tzinfo=UTC),
            symbols=[instrument.symbol],
            calendar_code=calendar.code,
            require_open_session=True,
        ),
    )
    assert [row.observation_time.day for row in dataset] == [2, 4]
    with pytest.raises(DatasetValidationError) as exc:
        get_daily_bars_dataset(
            db_session,
            build_daily_bars_dataset_request(
                as_of=datetime(2024, 1, 10, tzinfo=UTC),
                start_time=datetime(2024, 1, 1, tzinfo=UTC),
                end_time=datetime(2024, 1, 5, tzinfo=UTC),
                symbols=[instrument.symbol],
                calendar_code="NO_SUCH_CAL",
            ),
        )
    assert exc.value.code == DatasetErrorCode.UNKNOWN_CALENDAR


def test_dataset_incomplete_calendar_fails(db_session: Session) -> None:
    source = upsert_data_source(db_session, name=_unique("src"), vendor="local_csv")
    instrument = upsert_instrument(
        db_session, symbol=_unique("GAP"), asset_class="equity"
    )
    calendar = create_calendar(
        db_session, code=_unique("cal"), name="Sparse", timezone="UTC"
    )
    create_session(
        db_session,
        calendar_id=calendar.id,
        session_date=date(2024, 1, 2),
        session_kind="open",
    )
    run = create_ingestion_run(db_session, source_id=source.id)
    insert_daily_bars(
        db_session,
        drafts=[
            _draft(instrument.symbol, day=2, available_day=3, close="10"),
            _draft(instrument.symbol, day=3, available_day=4, close="11"),
        ],
        instruments_by_symbol={instrument.symbol: instrument},
        source_id=source.id,
        ingestion_run_id=run.id,
    )
    with pytest.raises(DatasetValidationError, match="no session row") as exc:
        get_daily_bars_dataset(
            db_session,
            build_daily_bars_dataset_request(
                as_of=datetime(2024, 1, 10, tzinfo=UTC),
                start_time=datetime(2024, 1, 1, tzinfo=UTC),
                end_time=datetime(2024, 1, 5, tzinfo=UTC),
                symbols=[instrument.symbol],
                calendar_code=calendar.code,
            ),
        )
    assert exc.value.code == DatasetErrorCode.INCOMPLETE_CALENDAR


def test_corporate_actions_visible_not_applied(db_session: Session) -> None:
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
    insert_daily_bars(
        db_session,
        drafts=[_draft(instrument.symbol, day=2, available_day=3, close="40")],
        instruments_by_symbol={instrument.symbol: instrument},
        source_id=source.id,
        ingestion_run_id=run.id,
    )
    create_corporate_action(
        db_session,
        instrument_id=instrument.id,
        action_type="split",
        effective_time=datetime(2024, 1, 2, tzinfo=UTC),
        available_time=datetime(2023, 12, 15, tzinfo=UTC),
        quantity_before=Decimal("1"),
        quantity_after=Decimal("4"),
        note="fictional 4-for-1",
    )
    create_corporate_action(
        db_session,
        instrument_id=instrument.id,
        action_type="dividend",
        effective_time=datetime(2024, 6, 1, tzinfo=UTC),
        available_time=datetime(2024, 5, 1, tzinfo=UTC),
        cash_amount=Decimal("0.25"),
    )
    request = build_daily_bars_dataset_request(
        as_of=datetime(2024, 1, 10, tzinfo=UTC),
        start_time=datetime(2024, 1, 1, tzinfo=UTC),
        end_time=datetime(2024, 1, 5, tzinfo=UTC),
        symbols=[instrument.symbol],
    )
    dataset = get_daily_bars_dataset(db_session, request)
    assert len(dataset) == 1
    assert dataset.rows[0].close == Decimal("40")
    actions = get_corporate_actions_for_dataset(db_session, request)
    assert [row.action_type for row in actions] == ["split"]
    assert actions[0].quantity_after == Decimal("4")
    hidden = get_corporate_actions_for_dataset(
        db_session,
        build_daily_bars_dataset_request(
            as_of=datetime(2023, 12, 1, tzinfo=UTC),
            start_time=datetime(2024, 1, 1, tzinfo=UTC),
            end_time=datetime(2024, 1, 5, tzinfo=UTC),
            symbols=[instrument.symbol],
        ),
    )
    assert hidden == ()
