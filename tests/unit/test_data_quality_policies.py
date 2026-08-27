"""Data-quality research policies without Docker. No signals or orders."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from quant_platform.backtest.artifacts import write_backtest_artifacts
from quant_platform.backtest.data_quality_policies import DataQualityResearchPolicy
from quant_platform.backtest.engine import execute_backtest
from quant_platform.backtest.errors import BacktestError, BacktestErrorCode
from quant_platform.backtest.observations import (
    ALLOWED_OBSERVATION_KINDS,
    FORBIDDEN_OPERATIVE_TOKENS,
    ResearchObservation,
    contains_operative_language,
    hash_policy_output,
)
from quant_platform.backtest.policy_interface import ResearchPolicy
from quant_platform.backtest.policy_output_integrity import verify_policy_output
from quant_platform.backtest.policy_registry import (
    get_research_policy,
    registered_policy_names,
)
from quant_platform.backtest.types import BacktestRequest
from quant_platform.research.types import (
    CorporateActionDatasetRow,
    DailyBarDatasetRow,
)
from quant_platform.simulation.constructs import (
    FORBIDDEN_TABLE_NAMES,
    detect_trading_constructs,
)
from quant_platform.simulation.events import (
    EVENT_PRIORITY,
    MarketSessionEvent,
    ReplayFinishedEvent,
    ReplayStartedEvent,
    corporate_action_event_from_row,
    market_bar_event_from_row,
)
from quant_platform.storage.database import Base

_DIGEST = "sha256:" + ("a" * 64)
_INSTANT = datetime(2024, 1, 3, tzinfo=UTC)
_INSTRUMENT = UUID("11111111-1111-4111-8111-111111111111")
_NEW_POLICIES = (
    "data_quality",
    "coverage",
    "corporate_action_audit",
    "correction_audit",
)


def _started() -> ReplayStartedEvent:
    return ReplayStartedEvent(
        event_time=_INSTANT,
        start_time=_INSTANT,
        end_time=datetime(2024, 1, 10, tzinfo=UTC),
        as_of=datetime(2024, 1, 10, tzinfo=UTC),
        instrument_count=1,
    )


def _finished() -> ReplayFinishedEvent:
    return ReplayFinishedEvent(
        event_time=datetime(2024, 1, 10, tzinfo=UTC),
        started_at=_INSTANT,
        finished_at=datetime(2024, 1, 10, tzinfo=UTC),
        event_count=5,
        bar_count=1,
        instrument_count=1,
    )


def _bar(
    *,
    day: int = 2,
    available_day: int = 3,
    is_correction: bool = False,
    instrument_id: UUID = _INSTRUMENT,
    symbol: str = "FICT",
) -> DailyBarDatasetRow:
    price = Decimal("10")
    return DailyBarDatasetRow(
        instrument_id=instrument_id,
        symbol=symbol,
        exchange_code="XNAS",
        asset_class="equity",
        currency="USD",
        observation_time=datetime(2024, 1, day, tzinfo=UTC),
        available_time=datetime(2024, 1, available_day, tzinfo=UTC),
        open=price,
        high=price + Decimal("1"),
        low=price - Decimal("1"),
        close=price,
        volume=Decimal("100"),
        source_name="local_csv",
        ingestion_run_id=uuid4(),
        is_correction=is_correction,
        correction_reason="late_print" if is_correction else None,
    )


def _action(*, action_type: str = "split") -> CorporateActionDatasetRow:
    return CorporateActionDatasetRow(
        instrument_id=_INSTRUMENT,
        symbol="FICT",
        exchange_code="XNAS",
        asset_class="equity",
        action_type=action_type,
        effective_time=datetime(2024, 1, 2, tzinfo=UTC),
        available_time=_INSTANT,
        quantity_before=Decimal("1"),
        quantity_after=Decimal("2"),
        cash_amount=None,
        currency="USD",
        old_value=None,
        new_value=None,
        note="fictional split",
    )


def _session(*, session_kind: str = "open", is_open: bool = True) -> MarketSessionEvent:
    return MarketSessionEvent(
        event_time=datetime(2024, 1, 2, tzinfo=UTC),
        session_date=date(2024, 1, 2),
        calendar_code="XNAS",
        exchange_code="XNAS",
        session_kind=session_kind,
        is_open=is_open,
        open_time=time(14, 30),
        close_time=time(21, 0),
        note=None,
    )


def _quality_events() -> tuple[object, ...]:
    return (
        _started(),
        _session(),
        _session(session_kind="holiday", is_open=False),
        corporate_action_event_from_row(_action()),
        market_bar_event_from_row(_bar()),
        market_bar_event_from_row(_bar(is_correction=True, available_day=6)),
        _finished(),
    )


def _config_for(name: str) -> dict[str, object] | None:
    if name == "data_quality":
        return {"emit_event_observations": True}
    if name == "corporate_action_audit":
        return {"emit_each_action": True}
    if name == "correction_audit":
        return {"emit_each_correction": True}
    return None


def _run(policy_name: str, events: tuple[object, ...], config=None):
    policy = get_research_policy(policy_name, config)
    for event in events:
        policy.observe(event)
    return policy.finalize()


def test_registry_accepts_quality_policies() -> None:
    names = registered_policy_names()
    for name in ("noop", "event_counting", *_NEW_POLICIES):
        assert name in names
        loaded = get_research_policy(name)
        assert isinstance(loaded, ResearchPolicy)
        assert loaded.name == name or name == "noop"
    with pytest.raises(BacktestError) as exc:
        get_research_policy("momentum")
    assert exc.value.code == BacktestErrorCode.INVALID_POLICY


def test_valid_and_invalid_configs() -> None:
    assert get_research_policy("data_quality", {"emit_event_observations": True})
    assert get_research_policy(
        "coverage",
        {
            "expected_instruments": ["FICT"],
            "min_bars_per_instrument": 1,
            "expected_dates": ["2024-01-02"],
            "max_gap_days": 2,
        },
    )
    assert get_research_policy(
        "corporate_action_audit",
        {"emit_each_action": True, "action_types": ["split"]},
    )
    assert get_research_policy("correction_audit", {"emit_each_correction": False})
    with pytest.raises(BacktestError):
        get_research_policy("data_quality", {"unknown_key": True})
    with pytest.raises(BacktestError):
        get_research_policy("data_quality", {"max_observations": -1})
    with pytest.raises(BacktestError):
        get_research_policy("coverage", {"min_bars_per_instrument": 0})
    with pytest.raises(BacktestError):
        get_research_policy("coverage", {"expected_dates": ["not-a-date"]})
    with pytest.raises(BacktestError):
        get_research_policy("coverage", {"expected_instruments": "FICT"})
    with pytest.raises(BacktestError):
        get_research_policy("data_quality", {"emit_event_observations": "yes"})


def test_data_quality_policy_produces_summary() -> None:
    output = _run("data_quality", _quality_events())
    kinds = {item.kind for item in output.observations}
    assert "data_quality_summary" in kinds
    summary = next(
        item for item in output.observations if item.kind == "data_quality_summary"
    )
    meta = summary.metadata
    assert meta["correction_count"] == 1
    assert meta["corporate_action_count"] == 1
    assert meta["holiday_session_count"] == 1
    assert meta["open_session_count"] >= 1
    assert output.summary.market_event_count == 2


def test_coverage_counts_bars_and_detects_expected_date_gap() -> None:
    events = (
        _started(),
        market_bar_event_from_row(_bar(day=2, available_day=3)),
        market_bar_event_from_row(_bar(day=5, available_day=6)),
        _finished(),
    )
    output = _run(
        "coverage",
        events,
        {
            "expected_dates": ["2024-01-02", "2024-01-03", "2024-01-05"],
            "max_gap_days": 1,
        },
    )
    kinds = {item.kind for item in output.observations}
    assert "coverage_summary" in kinds
    assert "instrument_seen" in kinds
    assert "coverage_gap" in kinds
    messages = [
        item.message for item in output.observations if item.kind == "coverage_gap"
    ]
    assert any("expected bar date was not seen" in item for item in messages)
    assert any("max_gap_days" in item for item in messages)


def test_corporate_action_audit_counts_actions() -> None:
    events = (
        _started(),
        corporate_action_event_from_row(_action()),
        corporate_action_event_from_row(_action(action_type="dividend")),
        _finished(),
    )
    output = _run(
        "corporate_action_audit",
        events,
        {"emit_each_action": True, "action_types": ["split"]},
    )
    summary = next(
        item for item in output.observations if item.kind == "corporate_action_summary"
    )
    assert summary.metadata["matched_count"] == 1
    assert summary.metadata["skipped_count"] == 1
    assert summary.metadata["counts_by_type"] == {"split": 1}
    seen = [
        item for item in output.observations if item.kind == "corporate_action_seen"
    ]
    assert len(seen) == 1


def test_correction_audit_detects_corrections() -> None:
    events = (
        _started(),
        market_bar_event_from_row(_bar()),
        market_bar_event_from_row(_bar(is_correction=True, available_day=6)),
        _finished(),
    )
    output = _run("correction_audit", events, {"emit_each_correction": True})
    summary = next(
        item for item in output.observations if item.kind == "correction_summary"
    )
    assert summary.metadata["correction_count"] == 1
    seen = [item for item in output.observations if item.kind == "correction_seen"]
    assert len(seen) == 1
    assert seen[0].metadata["is_correction"] is True


def test_hashes_are_stable_and_change_with_config() -> None:
    events = _quality_events()
    first = _run("data_quality", events)
    second = _run("data_quality", events)
    assert first.policy_output_hash == second.policy_output_hash
    assert hash_policy_output(first) == first.policy_output_hash
    changed = _run("data_quality", events, {"emit_event_observations": True})
    assert changed.policy_output_hash != first.policy_output_hash
    request = BacktestRequest(
        replay_id="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
        deterministic_id=True,
        policy_name="data_quality",
    )
    left = execute_backtest(events, request, stream_hash=_DIGEST)  # type: ignore[arg-type]
    right = execute_backtest(
        events,  # type: ignore[arg-type]
        BacktestRequest(
            replay_id="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
            deterministic_id=True,
            policy_name="data_quality",
            policy_config={"emit_summary_observations": False},
        ),
        stream_hash=_DIGEST,
    )
    assert left.summary.backtest_hash != right.summary.backtest_hash
    assert left.orders == ()
    assert left.fills == ()
    assert left.signals == ()


def test_observations_have_no_operative_language() -> None:
    for name in _NEW_POLICIES:
        output = _run(name, _quality_events(), _config_for(name))
        blob = json.dumps(output.as_mapping())
        assert contains_operative_language(blob) is False
        for item in output.observations:
            assert item.kind in ALLOWED_OBSERVATION_KINDS
            for token in FORBIDDEN_OPERATIVE_TOKENS:
                assert token not in item.kind
            assert "pnl" not in json.dumps(item.as_mapping()).lower()


def test_integrity_accepts_new_observation_kinds() -> None:
    kinds = (
        "data_quality_summary",
        "coverage_summary",
        "coverage_gap",
        "instrument_seen",
        "corporate_action_summary",
        "correction_summary",
        "temporal_consistency_warning",
    )
    for kind in kinds:
        severity = "warning" if kind == "coverage_gap" else "info"
        item = ResearchObservation(
            observation_time=_INSTANT,
            event_time=_INSTANT,
            kind=kind,
            message="quality note",
            severity=severity,
        )
        assert item.kind == kind


def test_integrity_accepts_written_quality_output(tmp_path: Path) -> None:
    result = execute_backtest(
        _quality_events(),  # type: ignore[arg-type]
        BacktestRequest(
            replay_id="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
            deterministic_id=True,
            policy_name="coverage",
            policy_config={"expected_dates": ["2024-01-02"]},
        ),
        stream_hash=_DIGEST,
    )
    written = write_backtest_artifacts(
        result,
        tmp_path / "bt",
        created_at=datetime(2024, 1, 10, tzinfo=UTC),
        git_commit="deadbeef",
        resolve_git=False,
    )
    assert written.manifest is not None
    report = verify_policy_output(tmp_path / "bt")
    assert report.ok is True
    payload = json.loads((tmp_path / "bt" / "policy_output.json").read_text())
    kinds = {item["kind"] for item in payload["observations"]}
    assert "coverage_summary" in kinds


def test_temporal_consistency_warning() -> None:
    late = market_bar_event_from_row(_bar(day=5, available_day=6))
    early = market_bar_event_from_row(_bar(day=2, available_day=3))
    output = _run("data_quality", (_started(), late, early, _finished()))
    kinds = {item.kind for item in output.observations}
    assert "temporal_consistency_warning" in kinds


def test_no_trading_constructs() -> None:
    findings = detect_trading_constructs(event_kinds=tuple(EVENT_PRIORITY))
    assert findings == ()
    names = set(Base.metadata.tables)
    assert names.isdisjoint(FORBIDDEN_TABLE_NAMES)
    assert names.isdisjoint({"portfolio", "orders", "fills"})
    assert "Strategy" not in DataQualityResearchPolicy.__name__
    assert "Signal" not in DataQualityResearchPolicy.__name__
