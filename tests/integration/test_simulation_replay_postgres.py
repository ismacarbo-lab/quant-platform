"""PostgreSQL daily-bar replay. No strategies, orders, or new tables."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from quant_platform.data.models import Instrument
from quant_platform.data.repository import (
    create_calendar,
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
from quant_platform.research.types import build_daily_bars_dataset_request
from quant_platform.simulation.events import MarketBarEvent
from quant_platform.simulation.replay import create_daily_bar_replay
from quant_platform.simulation.summary import SOURCE_DATABASE
from quant_platform.storage.database import list_public_tables

pytestmark = pytest.mark.postgres

_TRADING_TABLES = frozenset(
    {"trades", "orders", "fills", "signals", "strategies", "positions"}
)


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


def test_replay_basic_dataset(db_session: Session) -> None:
    source = upsert_data_source(db_session, name=_unique("src"), vendor="local_csv")
    venue = create_exchange(db_session, code=_unique("XNYS"), timezone="UTC")
    instrument = upsert_instrument(
        db_session,
        symbol=_unique("AAA"),
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
        close="10",
    )
    request = build_daily_bars_dataset_request(
        as_of=datetime(2024, 1, 10, tzinfo=UTC),
        start_time=datetime(2024, 1, 1, tzinfo=UTC),
        end_time=datetime(2024, 1, 5, tzinfo=UTC),
        symbols=[instrument.symbol],
    )
    replay = create_daily_bar_replay(db_session, request)
    assert replay.summary.source_type == SOURCE_DATABASE
    assert replay.summary.bar_count == 1
    assert replay.summary.event_count == 3
    assert replay.summary.instrument_count == 1
    bar = replay.bars[0]
    assert isinstance(bar, MarketBarEvent)
    assert bar.event_time == bar.available_time
    assert bar.close == Decimal("10")
    assert replay.summary.first_event_time == bar.event_time
    assert replay.summary.last_event_time == bar.event_time


def test_replay_emits_corrections_at_available_time(db_session: Session) -> None:
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
    late = create_daily_bar_replay(
        db_session,
        build_daily_bars_dataset_request(
            as_of=datetime(2024, 1, 6, tzinfo=UTC),
            start_time=datetime(2024, 1, 1, tzinfo=UTC),
            end_time=datetime(2024, 1, 10, tzinfo=UTC),
            symbols=[instrument.symbol],
        ),
    )
    assert late.summary.bar_count == 1
    bar = late.bars[0]
    assert bar.is_correction is True
    assert bar.close == Decimal("11")
    assert bar.event_time == datetime(2024, 1, 5, tzinfo=UTC)
    assert bar.observation_time == datetime(2024, 1, 1, tzinfo=UTC)


def test_replay_excludes_future_bars_vs_as_of(db_session: Session) -> None:
    source = upsert_data_source(db_session, name=_unique("src"), vendor="local_csv")
    venue = create_exchange(db_session, code=_unique("XNYS"), timezone="UTC")
    instrument = upsert_instrument(
        db_session,
        symbol=_unique("FUT"),
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
        close="10",
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
    replay = create_daily_bar_replay(
        db_session,
        build_daily_bars_dataset_request(
            as_of=datetime(2024, 1, 10, tzinfo=UTC),
            start_time=datetime(2024, 1, 1, tzinfo=UTC),
            end_time=datetime(2024, 1, 10, tzinfo=UTC),
            symbols=[instrument.symbol],
        ),
    )
    assert replay.summary.bar_count == 1
    assert all(bar.available_time <= replay.summary.as_of for bar in replay.bars)
    assert replay.bars[0].close == Decimal("10")


def test_replay_order_is_stable_across_instruments(db_session: Session) -> None:
    source = upsert_data_source(db_session, name=_unique("src"), vendor="local_csv")
    venue = create_exchange(db_session, code=_unique("XNYS"), timezone="UTC")
    late_symbol = _unique("AAA")
    early_symbol = _unique("ZZZ")
    late = upsert_instrument(
        db_session,
        symbol=late_symbol,
        asset_class="equity",
        exchange_id=venue.id,
        currency="USD",
    )
    early = upsert_instrument(
        db_session,
        symbol=early_symbol,
        asset_class="equity",
        exchange_id=venue.id,
        currency="USD",
    )
    run = create_ingestion_run(db_session, source_id=source.id)
    _insert_bar(
        db_session,
        instrument=late,
        source_id=source.id,
        ingestion_run_id=run.id,
        day=2,
        available_day=8,
        close="10",
    )
    _insert_bar(
        db_session,
        instrument=early,
        source_id=source.id,
        ingestion_run_id=run.id,
        day=3,
        available_day=4,
        close="20",
    )
    request = build_daily_bars_dataset_request(
        as_of=datetime(2024, 1, 10, tzinfo=UTC),
        start_time=datetime(2024, 1, 1, tzinfo=UTC),
        end_time=datetime(2024, 1, 5, tzinfo=UTC),
        symbols=[late_symbol, early_symbol],
    )
    first = create_daily_bar_replay(db_session, request)
    second = create_daily_bar_replay(db_session, request)
    symbols = [bar.symbol for bar in first.bars]
    assert symbols == [early_symbol, late_symbol]
    assert [bar.as_mapping() for bar in first.bars] == [
        bar.as_mapping() for bar in second.bars
    ]


def test_replay_respects_calendar_filter(db_session: Session) -> None:
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
    replay = create_daily_bar_replay(
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
    assert [bar.observation_time.day for bar in replay.bars] == [2, 4]
    assert replay.summary.bar_count == 2
    assert replay.summary.event_count == 4


def test_replay_does_not_create_tables(
    db_session: Session, postgres_engine: Engine
) -> None:
    before = set(list_public_tables(postgres_engine))
    source = upsert_data_source(db_session, name=_unique("src"), vendor="local_csv")
    instrument = upsert_instrument(
        db_session, symbol=_unique("TBL"), asset_class="equity"
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
    create_daily_bar_replay(
        db_session,
        build_daily_bars_dataset_request(
            as_of=datetime(2024, 1, 10, tzinfo=UTC),
            start_time=datetime(2024, 1, 1, tzinfo=UTC),
            end_time=datetime(2024, 1, 5, tzinfo=UTC),
            symbols=[instrument.symbol],
        ),
    )
    after = set(list_public_tables(postgres_engine))
    assert after == before
    assert after.isdisjoint(_TRADING_TABLES)
