"""PostgreSQL replay audit: sessions, corporate actions, stream hash."""

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
    create_corporate_action,
    create_exchange,
    create_ingestion_run,
    create_session,
    insert_daily_bars,
    upsert_data_source,
    upsert_instrument,
)
from quant_platform.data.validation import DailyBarDraft
from quant_platform.research.types import build_daily_bars_dataset_request
from quant_platform.simulation.audit import ReplayAuditCode, audit_replay
from quant_platform.simulation.events import (
    CORPORATE_ACTION_KIND,
    MARKET_BAR_KIND,
    MARKET_SESSION_KIND,
    CorporateActionEvent,
    MarketSessionEvent,
    ReplayStartedEvent,
)
from quant_platform.simulation.replay import create_daily_bar_replay
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


def test_replay_emits_visible_corporate_actions(db_session: Session) -> None:
    source = upsert_data_source(db_session, name=_unique("src"), vendor="local_csv")
    venue = create_exchange(db_session, code=_unique("XNYS"), timezone="UTC")
    instrument = upsert_instrument(
        db_session,
        symbol=_unique("CA"),
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
    replay = create_daily_bar_replay(
        db_session,
        build_daily_bars_dataset_request(
            as_of=datetime(2024, 1, 10, tzinfo=UTC),
            start_time=datetime(2024, 1, 1, tzinfo=UTC),
            end_time=datetime(2024, 1, 5, tzinfo=UTC),
            symbols=[instrument.symbol],
        ),
        include_corporate_actions=True,
    )
    assert replay.summary.corporate_action_count == 1
    assert isinstance(replay.events[0], ReplayStartedEvent)
    action = replay.corporate_actions[0]
    assert isinstance(action, CorporateActionEvent)
    assert action.action_type == "split"
    assert action.available_time == datetime(2023, 12, 15, tzinfo=UTC)
    assert action.event_time == datetime(2024, 1, 1, tzinfo=UTC)
    assert action.known_before_start is True
    assert replay.events[1] is action
    assert replay.bars[0].close == Decimal("40")


def test_replay_excludes_future_corporate_actions(db_session: Session) -> None:
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
    create_corporate_action(
        db_session,
        instrument_id=instrument.id,
        action_type="dividend",
        effective_time=datetime(2024, 1, 2, tzinfo=UTC),
        available_time=datetime(2024, 1, 20, tzinfo=UTC),
        cash_amount=Decimal("1.00"),
    )
    replay = create_daily_bar_replay(
        db_session,
        build_daily_bars_dataset_request(
            as_of=datetime(2024, 1, 10, tzinfo=UTC),
            start_time=datetime(2024, 1, 1, tzinfo=UTC),
            end_time=datetime(2024, 1, 5, tzinfo=UTC),
            symbols=[instrument.symbol],
        ),
        include_corporate_actions=True,
    )
    assert replay.summary.corporate_action_count == 0
    assert all(event.event_time <= replay.summary.as_of for event in replay.events)


def test_replay_emits_holiday_and_exceptional_close_sessions(
    db_session: Session,
) -> None:
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
    create_session(
        db_session,
        calendar_id=calendar.id,
        session_date=date(2024, 1, 5),
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
        day=2,
        available_day=3,
        close="10",
    )
    replay = create_daily_bar_replay(
        db_session,
        build_daily_bars_dataset_request(
            as_of=datetime(2024, 1, 10, tzinfo=UTC),
            start_time=datetime(2024, 1, 1, tzinfo=UTC),
            end_time=datetime(2024, 1, 5, tzinfo=UTC),
            symbols=[instrument.symbol],
            calendar_code=calendar.code,
        ),
        include_sessions=True,
    )
    kinds = [event.session_kind for event in replay.sessions]
    assert kinds == ["open", "holiday", "half_session", "exceptional_close"]
    closed = [
        event
        for event in replay.sessions
        if event.session_kind in {"holiday", "exceptional_close"}
    ]
    assert all(isinstance(event, MarketSessionEvent) for event in closed)
    assert all(event.is_open is False for event in closed)


def test_replay_multi_event_order_is_stable(db_session: Session) -> None:
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
        session_kind="open",
    )
    instrument = upsert_instrument(
        db_session,
        symbol=_unique("ORD"),
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
        day=2,
        available_day=3,
        close="10",
    )
    create_corporate_action(
        db_session,
        instrument_id=instrument.id,
        action_type="split",
        effective_time=datetime(2024, 1, 2, tzinfo=UTC),
        available_time=datetime(2024, 1, 3, tzinfo=UTC),
        quantity_before=Decimal("1"),
        quantity_after=Decimal("2"),
    )
    request = build_daily_bars_dataset_request(
        as_of=datetime(2024, 1, 10, tzinfo=UTC),
        start_time=datetime(2024, 1, 1, tzinfo=UTC),
        end_time=datetime(2024, 1, 5, tzinfo=UTC),
        symbols=[instrument.symbol],
        calendar_code=calendar.code,
    )
    first = create_daily_bar_replay(
        db_session,
        request,
        include_corporate_actions=True,
        include_sessions=True,
        deterministic_id=True,
    )
    second = create_daily_bar_replay(
        db_session,
        request,
        include_corporate_actions=True,
        include_sessions=True,
        deterministic_id=True,
    )
    kinds = [event.kind for event in first.events]
    assert kinds[0] != MARKET_BAR_KIND
    assert MARKET_SESSION_KIND in kinds
    assert CORPORATE_ACTION_KIND in kinds
    assert kinds.index(CORPORATE_ACTION_KIND) < kinds.index(MARKET_BAR_KIND)
    assert [event.as_mapping() for event in first.events] == [
        event.as_mapping() for event in second.events
    ]
    assert first.summary.stream_hash == second.summary.stream_hash
    assert first.summary.replay_id == second.summary.replay_id


def test_audit_report_clean_for_valid_replay(db_session: Session) -> None:
    source = upsert_data_source(db_session, name=_unique("src"), vendor="local_csv")
    venue = create_exchange(db_session, code=_unique("XNYS"), timezone="UTC")
    calendar = create_calendar(
        db_session, code=_unique("cal"), name="Test", timezone="UTC"
    )
    for day, kind in (
        (2, "open"),
        (3, "open"),
        (4, "open"),
        (5, "open"),
    ):
        create_session(
            db_session,
            calendar_id=calendar.id,
            session_date=date(2024, 1, day),
            session_kind=kind,
        )
    instrument = upsert_instrument(
        db_session,
        symbol=_unique("OK"),
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
        day=2,
        available_day=3,
        close="10",
    )
    replay = create_daily_bar_replay(
        db_session,
        build_daily_bars_dataset_request(
            as_of=datetime(2024, 1, 10, tzinfo=UTC),
            start_time=datetime(2024, 1, 2, tzinfo=UTC),
            end_time=datetime(2024, 1, 5, tzinfo=UTC),
            symbols=[instrument.symbol],
            calendar_code=calendar.code,
        ),
        include_sessions=True,
        include_corporate_actions=True,
    )
    report = audit_replay(
        replay.events,
        as_of=replay.summary.as_of,
        sessions_requested=True,
        calendar_code=calendar.code,
    )
    assert report.ok is True
    assert report.error_count == 0
    assert report.stream_hash == replay.summary.stream_hash


def test_audit_detects_artificial_out_of_order(db_session: Session) -> None:
    source = upsert_data_source(db_session, name=_unique("src"), vendor="local_csv")
    instrument = upsert_instrument(
        db_session, symbol=_unique("BAD"), asset_class="equity"
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
    replay = create_daily_bar_replay(
        db_session,
        build_daily_bars_dataset_request(
            as_of=datetime(2024, 1, 10, tzinfo=UTC),
            start_time=datetime(2024, 1, 1, tzinfo=UTC),
            end_time=datetime(2024, 1, 5, tzinfo=UTC),
            symbols=[instrument.symbol],
        ),
    )
    swapped = (replay.events[-1], *replay.events[:-1])
    report = audit_replay(swapped, as_of=replay.summary.as_of)
    assert report.ok is False
    assert any(item.code == ReplayAuditCode.OUT_OF_ORDER for item in report.issues)


def test_audit_replay_does_not_create_tables(
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
        include_corporate_actions=True,
        include_sessions=True,
        deterministic_id=True,
    )
    after = set(list_public_tables(postgres_engine))
    assert after == before
    assert after.isdisjoint(_TRADING_TABLES)
