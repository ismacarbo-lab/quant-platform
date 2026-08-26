"""Replay stream hash, event priority, and audit without Docker."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal
from uuid import UUID, uuid4

from quant_platform.research.types import (
    CorporateActionDatasetRow,
    DailyBarDatasetRow,
    DailyBarsDataset,
    build_daily_bars_dataset_request,
)
from quant_platform.simulation.audit import ReplayAuditCode, audit_replay
from quant_platform.simulation.events import (
    CORPORATE_ACTION_KIND,
    EVENT_PRIORITY,
    MARKET_BAR_KIND,
    MARKET_SESSION_KIND,
    REPLAY_FINISHED_KIND,
    REPLAY_STARTED_KIND,
    MarketSessionEvent,
    ReplayFinishedEvent,
    ReplayStartedEvent,
    corporate_action_event_from_row,
    replay_event_sort_key,
)
from quant_platform.simulation.hashing import (
    derive_replay_id,
    hash_replay_events,
    hash_replay_request,
)
from quant_platform.simulation.replay import replay_daily_bars_dataset


def _bar(**overrides: object) -> DailyBarDatasetRow:
    values: dict[str, object] = {
        "instrument_id": uuid4(),
        "symbol": "FICT",
        "exchange_code": "XNAS",
        "asset_class": "equity",
        "currency": "USD",
        "observation_time": datetime(2024, 1, 2, tzinfo=UTC),
        "available_time": datetime(2024, 1, 3, tzinfo=UTC),
        "open": Decimal("10"),
        "high": Decimal("11"),
        "low": Decimal("9"),
        "close": Decimal("10.5"),
        "volume": Decimal("100"),
        "source_name": "local_csv",
        "ingestion_run_id": uuid4(),
        "is_correction": False,
        "correction_reason": None,
    }
    values.update(overrides)
    return DailyBarDatasetRow(**values)  # type: ignore[arg-type]


def _action(**overrides: object) -> CorporateActionDatasetRow:
    values: dict[str, object] = {
        "instrument_id": uuid4(),
        "symbol": "FICT",
        "exchange_code": "XNAS",
        "asset_class": "equity",
        "action_type": "split",
        "effective_time": datetime(2024, 1, 2, tzinfo=UTC),
        "available_time": datetime(2024, 1, 3, tzinfo=UTC),
        "quantity_before": Decimal("1"),
        "quantity_after": Decimal("2"),
        "cash_amount": None,
        "currency": "USD",
        "old_value": None,
        "new_value": None,
        "note": "fictional 2-for-1",
    }
    values.update(overrides)
    return CorporateActionDatasetRow(**values)  # type: ignore[arg-type]


def _request(**overrides: object):
    values: dict[str, object] = {
        "as_of": datetime(2024, 1, 10, tzinfo=UTC),
        "start_time": datetime(2024, 1, 1, tzinfo=UTC),
        "end_time": datetime(2024, 1, 5, tzinfo=UTC),
        "symbols": ["FICT"],
    }
    values.update(overrides)
    return build_daily_bars_dataset_request(**values)  # type: ignore[arg-type]


def _dataset(
    rows: tuple[DailyBarDatasetRow, ...], **request_overrides: object
) -> DailyBarsDataset:
    return DailyBarsDataset(request=_request(**request_overrides), rows=rows)


def _session(**overrides: object) -> MarketSessionEvent:
    values: dict[str, object] = {
        "event_time": datetime(2024, 1, 3, tzinfo=UTC),
        "session_date": date(2024, 1, 3),
        "calendar_code": "XNYS",
        "exchange_code": None,
        "session_kind": "open",
        "is_open": True,
        "open_time": time(14, 30),
        "close_time": time(21, 0),
        "note": None,
    }
    values.update(overrides)
    return MarketSessionEvent(**values)  # type: ignore[arg-type]


def test_event_priority_order_on_tied_event_time() -> None:
    instant = datetime(2024, 1, 3, tzinfo=UTC)
    instrument = uuid4()
    session = _session(event_time=instant, session_date=date(2024, 1, 3))
    action = corporate_action_event_from_row(
        _action(instrument_id=instrument, available_time=instant)
    )
    bar = replay_daily_bars_dataset(
        _dataset(
            (
                _bar(
                    instrument_id=instrument,
                    available_time=instant,
                    observation_time=datetime(2024, 1, 2, tzinfo=UTC),
                ),
            )
        )
    ).bars[0]
    started = ReplayStartedEvent(
        event_time=instant,
        start_time=instant,
        end_time=instant,
        as_of=datetime(2024, 1, 10, tzinfo=UTC),
        instrument_count=1,
    )
    finished = ReplayFinishedEvent(
        event_time=instant,
        started_at=instant,
        finished_at=instant,
        event_count=5,
        bar_count=1,
        instrument_count=1,
    )
    ordered = tuple(
        sorted(
            (finished, bar, action, session, started),
            key=replay_event_sort_key,
        )
    )
    assert [event.kind for event in ordered] == [
        REPLAY_STARTED_KIND,
        MARKET_SESSION_KIND,
        CORPORATE_ACTION_KIND,
        MARKET_BAR_KIND,
        REPLAY_FINISHED_KIND,
    ]
    assert EVENT_PRIORITY[MARKET_SESSION_KIND] < EVENT_PRIORITY[MARKET_BAR_KIND]


def test_stream_hash_is_stable_and_ignores_replay_id() -> None:
    row = _bar()
    dataset = _dataset((row,))
    first = replay_daily_bars_dataset(
        dataset, replay_id=UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    )
    second = replay_daily_bars_dataset(
        dataset, replay_id=UUID("ffffffff-eeee-dddd-cccc-bbbbbbbbbbbb")
    )
    assert first.summary.stream_hash == second.summary.stream_hash
    assert hash_replay_events(first.events) == hash_replay_events(second.events)
    assert first.summary.replay_id != second.summary.replay_id
    assert "replay_id" not in hash_replay_events(first.events)


def test_stream_hash_changes_when_price_changes() -> None:
    shared_id = uuid4()
    cheap = _bar(instrument_id=shared_id, close=Decimal("10.5"))
    dear = _bar(
        instrument_id=shared_id,
        ingestion_run_id=cheap.ingestion_run_id,
        observation_time=cheap.observation_time,
        available_time=cheap.available_time,
        close=Decimal("11.5"),
        high=Decimal("12"),
    )
    left = replay_daily_bars_dataset(_dataset((cheap,)))
    right = replay_daily_bars_dataset(_dataset((dear,)))
    assert left.summary.stream_hash != right.summary.stream_hash


def test_corporate_action_event_uses_available_time() -> None:
    row = _action(
        available_time=datetime(2024, 1, 8, tzinfo=UTC),
        effective_time=datetime(2024, 1, 2, tzinfo=UTC),
    )
    event = corporate_action_event_from_row(row)
    assert event.event_time == event.available_time
    assert event.event_time != event.effective_time
    replay = replay_daily_bars_dataset(
        _dataset((_bar(symbol="FICT"),)),
        corporate_actions=(row,),
        include_corporate_actions=True,
    )
    assert replay.summary.corporate_action_count == 1
    assert replay.corporate_actions[0].event_time == row.available_time
    assert replay.bars[0].close == Decimal("10.5")


def test_session_event_serializes() -> None:
    event = _session(note="half day")
    mapping = event.as_mapping()
    assert mapping["kind"] == MARKET_SESSION_KIND
    assert mapping["session_date"] == "2024-01-03"
    assert mapping["open_time"] == "14:30:00"
    assert mapping["is_open"] is True
    replay = replay_daily_bars_dataset(
        _dataset((_bar(),)),
        session_events=(event,),
        include_sessions=True,
    )
    assert replay.summary.session_count == 1
    assert replay.sessions[0].calendar_code == "XNYS"


def test_audit_detects_out_of_order_events() -> None:
    replay = replay_daily_bars_dataset(_dataset((_bar(),)))
    swapped = (replay.events[-1], *replay.events[1:-1], replay.events[0])
    report = audit_replay(swapped, as_of=replay.summary.as_of)
    assert report.ok is False
    assert any(item.code == ReplayAuditCode.OUT_OF_ORDER for item in report.issues)


def test_audit_detects_lookahead() -> None:
    row = _bar(available_time=datetime(2024, 1, 8, tzinfo=UTC))
    replay = replay_daily_bars_dataset(_dataset((row,)))
    report = audit_replay(replay.events, as_of=datetime(2024, 1, 4, tzinfo=UTC))
    assert report.ok is False
    assert any(item.code == ReplayAuditCode.LOOKAHEAD for item in report.issues)


def test_deterministic_replay_id_is_stable() -> None:
    dataset = _dataset((_bar(),))
    first = replay_daily_bars_dataset(dataset, deterministic_id=True)
    second = replay_daily_bars_dataset(dataset, deterministic_id=True)
    assert first.summary.replay_id == second.summary.replay_id
    assert first.summary.stream_hash is not None
    derived = derive_replay_id(
        first.summary.stream_hash, hash_replay_request(dataset.request)
    )
    assert first.summary.replay_id == derived
    third = replay_daily_bars_dataset(dataset, replay_id=derived, deterministic_id=True)
    assert third.summary.replay_id == derived


def test_no_order_or_trading_events_exist() -> None:
    import quant_platform.simulation.events as events_mod

    names = {name for name in dir(events_mod) if name.endswith("Event")}
    for forbidden in ("Order", "Trade", "Fill", "Signal", "Position", "Portfolio"):
        assert all(forbidden not in name for name in names)
    replay = replay_daily_bars_dataset(_dataset((_bar(),)))
    report = audit_replay(replay.events, as_of=replay.summary.as_of)
    assert report.ok is True
    dumped = hash_replay_events(replay.events)
    assert dumped.startswith("sha256:")
    assert "order" not in dumped
    assert "trade" not in dumped
