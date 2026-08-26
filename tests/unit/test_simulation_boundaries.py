"""Replay boundary semantics and event fixtures without Docker."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from quant_platform.research.types import (
    CorporateActionDatasetRow,
    DailyBarDatasetRow,
    DailyBarsDataset,
    build_daily_bars_dataset_request,
)
from quant_platform.simulation.audit import ReplayAuditCode, audit_replay
from quant_platform.simulation.event_fixtures import (
    load_replay_events_json,
    replay_event_fixtures_dir,
)
from quant_platform.simulation.events import (
    CORPORATE_ACTION_KIND,
    MARKET_BAR_KIND,
    MARKET_SESSION_KIND,
    REPLAY_FINISHED_KIND,
    REPLAY_STARTED_KIND,
    CorporateActionEvent,
    MarketBarEvent,
    MarketSessionEvent,
    ReplayFinishedEvent,
    ReplayStartedEvent,
    apply_start_boundary,
    corporate_action_event_from_row,
    is_pre_known_event,
)
from quant_platform.simulation.hashing import hash_replay_events
from quant_platform.simulation.replay import replay_daily_bars_dataset

_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "replay_events"
_FIXTURE_NAMES = (
    "simple_daily_replay.json",
    "corporate_action_preknown.json",
    "calendar_sessions_replay.json",
    "correction_replay.json",
)
_TRADING_FRAGMENTS = ("order", "trade", "fill", "signal", "position", "portfolio")


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
        "available_time": datetime(2023, 12, 15, tzinfo=UTC),
        "quantity_before": Decimal("1"),
        "quantity_after": Decimal("4"),
        "cash_amount": None,
        "currency": "USD",
        "old_value": None,
        "new_value": None,
        "note": "fictional 4-for-1",
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


def _preknown_replay():
    row = _bar()
    action = _action(instrument_id=row.instrument_id, symbol=row.symbol)
    return replay_daily_bars_dataset(
        _dataset((row,)),
        corporate_actions=(action,),
        include_corporate_actions=True,
    )


def test_replay_started_event_is_always_first() -> None:
    replay = _preknown_replay()
    assert isinstance(replay.events[0], ReplayStartedEvent)
    assert replay.events[0].kind == REPLAY_STARTED_KIND
    assert all(event.event_time >= replay.summary.start_time for event in replay.events)


def test_replay_finished_event_is_always_last() -> None:
    replay = _preknown_replay()
    assert isinstance(replay.events[-1], ReplayFinishedEvent)
    assert replay.events[-1].kind == REPLAY_FINISHED_KIND


def test_preknown_corporate_action_appears_after_started() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    available = datetime(2023, 12, 15, tzinfo=UTC)
    replay = _preknown_replay()
    assert replay.events[0].kind == REPLAY_STARTED_KIND
    action = replay.corporate_actions[0]
    assert replay.events[1] is action
    assert action.known_before_start is True
    assert action.available_time == available
    assert action.event_time == start
    assert action.event_time != action.available_time
    assert is_pre_known_event(action)
    report = audit_replay(replay.events, as_of=replay.summary.as_of)
    assert report.ok is True
    assert report.boundary_ok is True


def test_stream_hash_is_stable_with_preknown_facts() -> None:
    row = _bar()
    action = _action(instrument_id=row.instrument_id, symbol=row.symbol)
    dataset = _dataset((row,))
    first = replay_daily_bars_dataset(
        dataset,
        corporate_actions=(action,),
        include_corporate_actions=True,
    )
    second = replay_daily_bars_dataset(
        dataset,
        corporate_actions=(action,),
        include_corporate_actions=True,
    )
    assert first.summary.stream_hash == second.summary.stream_hash
    assert hash_replay_events(first.events) == first.summary.stream_hash
    dumped = hash_replay_events(first.events)
    assert dumped.startswith("sha256:")
    assert "replay_id" not in dumped
    assert str(first.summary.replay_id) not in dumped


def test_audit_detects_missing_started() -> None:
    replay = replay_daily_bars_dataset(_dataset((_bar(),)))
    report = audit_replay(replay.events[1:], as_of=replay.summary.as_of)
    assert report.ok is False
    assert report.starts_with_replay_started is False
    assert report.boundary_ok is False
    assert any(item.code == ReplayAuditCode.MISSING_STARTED for item in report.issues)


def test_audit_detects_missing_finished() -> None:
    replay = replay_daily_bars_dataset(_dataset((_bar(),)))
    report = audit_replay(replay.events[:-1], as_of=replay.summary.as_of)
    assert report.ok is False
    assert report.ends_with_replay_finished is False
    assert report.boundary_ok is False
    assert any(item.code == ReplayAuditCode.MISSING_FINISHED for item in report.issues)


def test_audit_detects_preknown_misplaced() -> None:
    replay = _preknown_replay()
    started, action, bar, finished = replay.events
    assert isinstance(action, CorporateActionEvent)
    assert isinstance(bar, MarketBarEvent)
    misplaced = (started, bar, action, finished)
    report = audit_replay(misplaced, as_of=replay.summary.as_of)
    assert report.ok is False
    assert any(
        item.code == ReplayAuditCode.PREKNOWN_MISPLACED for item in report.issues
    )


def test_audit_detects_preknown_unmarked_and_event_before_start() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    row = _bar()
    native = corporate_action_event_from_row(
        _action(
            instrument_id=row.instrument_id,
            symbol=row.symbol,
            available_time=datetime(2023, 12, 15, tzinfo=UTC),
        )
    )
    replay = replay_daily_bars_dataset(_dataset((row,)))
    unmarked = (replay.events[0], native, replay.bars[0], replay.events[-1])
    report = audit_replay(unmarked, as_of=replay.summary.as_of, start_time=start)
    codes = {item.code for item in report.issues}
    assert ReplayAuditCode.PREKNOWN_UNMARKED in codes
    assert ReplayAuditCode.EVENT_BEFORE_START in codes
    assert report.boundary_ok is False


def test_summary_counts_preknown_facts() -> None:
    replay = _preknown_replay()
    assert replay.summary.pre_known_event_count == 1
    assert replay.summary.market_event_count == 1
    assert replay.summary.session_event_count == 0
    assert replay.summary.corporate_action_event_count == 1
    assert replay.summary.first_market_event_time == replay.bars[0].event_time
    assert replay.summary.last_market_event_time == replay.bars[0].event_time
    mapping = replay.summary.as_mapping()
    assert mapping["pre_known_event_count"] == 1
    assert mapping["market_event_count"] == 1


def test_apply_start_boundary_clamps_session_before_start() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    session = MarketSessionEvent(
        event_time=datetime(2023, 12, 31, tzinfo=UTC),
        session_date=date(2023, 12, 31),
        calendar_code="XNYS",
        exchange_code=None,
        session_kind="open",
        is_open=True,
        open_time=time(14, 30),
        close_time=time(21, 0),
        note=None,
    )
    clamped = apply_start_boundary(session, start)
    assert isinstance(clamped, MarketSessionEvent)
    assert clamped.known_before_start is True
    assert clamped.event_time == start
    assert clamped.session_date == date(2023, 12, 31)
    replay = replay_daily_bars_dataset(
        _dataset((_bar(),)),
        session_events=(session,),
        include_sessions=True,
    )
    assert isinstance(replay.events[0], ReplayStartedEvent)
    assert isinstance(replay.events[-1], ReplayFinishedEvent)
    assert replay.sessions[0].known_before_start is True
    assert replay.sessions[0].event_time == start


def test_replay_event_json_fixtures_are_valid() -> None:
    discovered = replay_event_fixtures_dir()
    assert discovered == _FIXTURE_DIR
    as_of = datetime(2024, 1, 10, tzinfo=UTC)
    for name in _FIXTURE_NAMES:
        loaded = load_replay_events_json(_FIXTURE_DIR / name)
        assert loaded.description
        assert isinstance(loaded.events[0], ReplayStartedEvent)
        assert isinstance(loaded.events[-1], ReplayFinishedEvent)
        kinds = [event.kind for event in loaded.events]
        assert kinds[0] == REPLAY_STARTED_KIND
        assert kinds[-1] == REPLAY_FINISHED_KIND
        assert MARKET_BAR_KIND in kinds
        for fragment in _TRADING_FRAGMENTS:
            assert all(fragment not in kind for kind in kinds)
        dumped = hash_replay_events(loaded.events)
        assert dumped.startswith("sha256:")
        report = audit_replay(loaded.events, as_of=as_of)
        assert report.ok is True
        assert report.boundary_ok is True


def test_preknown_fixture_keeps_original_available_time() -> None:
    loaded = load_replay_events_json(_FIXTURE_DIR / "corporate_action_preknown.json")
    action = next(
        event for event in loaded.events if isinstance(event, CorporateActionEvent)
    )
    assert action.known_before_start is True
    assert action.available_time == datetime(2023, 12, 15, tzinfo=UTC)
    assert action.event_time == datetime(2024, 1, 1, tzinfo=UTC)
    assert loaded.events[1] is action


def test_no_trading_events_in_boundary_module() -> None:
    import quant_platform.simulation.events as events_mod

    names = {name for name in dir(events_mod) if name.endswith("Event")}
    for forbidden in ("Order", "Trade", "Fill", "Signal", "Position", "Portfolio"):
        assert all(forbidden not in name for name in names)
    replay = _preknown_replay()
    kinds = {event.kind for event in replay.events}
    assert kinds == {
        REPLAY_STARTED_KIND,
        CORPORATE_ACTION_KIND,
        MARKET_BAR_KIND,
        REPLAY_FINISHED_KIND,
    }
    assert MARKET_SESSION_KIND not in kinds
    dumped = hash_replay_events(replay.events)
    for fragment in _TRADING_FRAGMENTS:
        assert fragment not in dumped
