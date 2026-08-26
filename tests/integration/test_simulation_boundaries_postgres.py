"""PostgreSQL replay boundary: pre-known facts stay after ReplayStartedEvent."""

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
from quant_platform.simulation.audit import audit_replay
from quant_platform.simulation.events import (
    CorporateActionEvent,
    ReplayFinishedEvent,
    ReplayStartedEvent,
)
from quant_platform.simulation.hashing import hash_replay_events
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


def _seed_instrument(
    db_session: Session, *, prefix: str
) -> tuple[Instrument, UUID, UUID]:
    source = upsert_data_source(db_session, name=_unique("src"), vendor="local_csv")
    venue = create_exchange(db_session, code=_unique("XNYS"), timezone="UTC")
    instrument = upsert_instrument(
        db_session,
        symbol=_unique(prefix),
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
    return instrument, source.id, run.id


def test_preknown_corporate_action_stays_after_started(db_session: Session) -> None:
    instrument, _, _ = _seed_instrument(db_session, prefix="PRE")
    start = datetime(2024, 1, 1, tzinfo=UTC)
    available = datetime(2023, 12, 15, tzinfo=UTC)
    create_corporate_action(
        db_session,
        instrument_id=instrument.id,
        action_type="split",
        effective_time=datetime(2024, 1, 2, tzinfo=UTC),
        available_time=available,
        quantity_before=Decimal("1"),
        quantity_after=Decimal("4"),
        note="fictional 4-for-1",
    )
    replay = create_daily_bar_replay(
        db_session,
        build_daily_bars_dataset_request(
            as_of=datetime(2024, 1, 10, tzinfo=UTC),
            start_time=start,
            end_time=datetime(2024, 1, 5, tzinfo=UTC),
            symbols=[instrument.symbol],
        ),
        include_corporate_actions=True,
    )
    assert isinstance(replay.events[0], ReplayStartedEvent)
    assert isinstance(replay.events[-1], ReplayFinishedEvent)
    action = replay.corporate_actions[0]
    assert isinstance(action, CorporateActionEvent)
    assert replay.events[1] is action
    assert action.known_before_start is True
    assert action.available_time == available
    assert action.event_time == start
    assert replay.summary.pre_known_event_count == 1


def test_in_window_corporate_action_keeps_available_time(db_session: Session) -> None:
    instrument, _, _ = _seed_instrument(db_session, prefix="WIN")
    available = datetime(2024, 1, 3, tzinfo=UTC)
    create_corporate_action(
        db_session,
        instrument_id=instrument.id,
        action_type="dividend",
        effective_time=datetime(2024, 1, 2, tzinfo=UTC),
        available_time=available,
        cash_amount=Decimal("0.25"),
        currency="USD",
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
    action = replay.corporate_actions[0]
    assert action.known_before_start is False
    assert action.event_time == available
    assert action.available_time == available
    assert replay.summary.pre_known_event_count == 0


def test_future_corporate_action_is_not_visible(db_session: Session) -> None:
    instrument, _, _ = _seed_instrument(db_session, prefix="FUT")
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
    assert replay.summary.corporate_action_event_count == 0
    assert all(event.event_time <= replay.summary.as_of for event in replay.events)


def test_session_replay_keeps_started_and_finished_bookends(
    db_session: Session,
) -> None:
    instrument, _, _ = _seed_instrument(db_session, prefix="SES")
    calendar = create_calendar(
        db_session, code=_unique("cal"), name="Test", timezone="UTC"
    )
    create_session(
        db_session,
        calendar_id=calendar.id,
        session_date=date(2024, 1, 2),
        session_kind="open",
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
    assert isinstance(replay.events[0], ReplayStartedEvent)
    assert isinstance(replay.events[-1], ReplayFinishedEvent)
    assert replay.summary.session_event_count == 1
    assert replay.sessions[0].known_before_start is False
    report = audit_replay(
        replay.events,
        as_of=replay.summary.as_of,
        sessions_requested=True,
        calendar_code=calendar.code,
    )
    assert report.ok is True
    assert report.boundary_ok is True


def test_valid_boundary_stream_has_clean_audit_and_stable_hash(
    db_session: Session,
) -> None:
    instrument, _, _ = _seed_instrument(db_session, prefix="OK")
    create_corporate_action(
        db_session,
        instrument_id=instrument.id,
        action_type="split",
        effective_time=datetime(2024, 1, 2, tzinfo=UTC),
        available_time=datetime(2023, 12, 15, tzinfo=UTC),
        quantity_before=Decimal("1"),
        quantity_after=Decimal("2"),
    )
    request = build_daily_bars_dataset_request(
        as_of=datetime(2024, 1, 10, tzinfo=UTC),
        start_time=datetime(2024, 1, 1, tzinfo=UTC),
        end_time=datetime(2024, 1, 5, tzinfo=UTC),
        symbols=[instrument.symbol],
    )
    first = create_daily_bar_replay(
        db_session,
        request,
        include_corporate_actions=True,
        deterministic_id=True,
    )
    second = create_daily_bar_replay(
        db_session,
        request,
        include_corporate_actions=True,
        deterministic_id=True,
    )
    report = audit_replay(first.events, as_of=first.summary.as_of)
    assert report.ok is True
    assert report.boundary_ok is True
    assert report.error_count == 0
    assert first.summary.stream_hash == second.summary.stream_hash
    assert hash_replay_events(first.events) == first.summary.stream_hash
    assert first.summary.replay_id == second.summary.replay_id


def test_boundary_replay_does_not_create_tables(
    db_session: Session, postgres_engine: Engine
) -> None:
    before = set(list_public_tables(postgres_engine))
    instrument, _, _ = _seed_instrument(db_session, prefix="TBL")
    create_corporate_action(
        db_session,
        instrument_id=instrument.id,
        action_type="split",
        effective_time=datetime(2024, 1, 2, tzinfo=UTC),
        available_time=datetime(2023, 12, 15, tzinfo=UTC),
        quantity_before=Decimal("1"),
        quantity_after=Decimal("2"),
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
