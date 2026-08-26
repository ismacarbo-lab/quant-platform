"""Research policy interface without Docker. No signals or orders."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from quant_platform.backtest.artifacts import write_backtest_artifacts
from quant_platform.backtest.compare import BacktestRunDiffVerdict, diff_backtest_runs
from quant_platform.backtest.engine import execute_backtest
from quant_platform.backtest.errors import BacktestError, BacktestErrorCode
from quant_platform.backtest.observations import (
    ALLOWED_OBSERVATION_KINDS,
    FORBIDDEN_OPERATIVE_TOKENS,
    ResearchObservation,
    contains_operative_language,
    hash_policy_output,
    normalize_policy_config,
)
from quant_platform.backtest.policy import (
    EventCountingBacktestPolicy,
    EventCountingResearchPolicy,
    NoOpBacktestPolicy,
)
from quant_platform.backtest.policy_interface import ResearchPolicy
from quant_platform.backtest.policy_registry import (
    get_research_policy,
    registered_policy_names,
)
from quant_platform.backtest.types import BacktestRequest
from quant_platform.simulation.constructs import (
    FORBIDDEN_TABLE_NAMES,
    detect_trading_constructs,
)
from quant_platform.simulation.events import (
    EVENT_PRIORITY,
    ReplayFinishedEvent,
    ReplayStartedEvent,
)
from quant_platform.storage.database import Base

_DIGEST = "sha256:" + ("a" * 64)
_INSTANT = datetime(2024, 1, 3, tzinfo=UTC)


def _request(**overrides: object) -> BacktestRequest:
    values: dict[str, object] = {
        "replay_id": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
        "deterministic_id": True,
        "policy_name": "noop",
        "policy_config": None,
        "notes": None,
    }
    values.update(overrides)
    return BacktestRequest(**values)  # type: ignore[arg-type]


def _events() -> tuple[ReplayStartedEvent | ReplayFinishedEvent | str, ...]:
    started = ReplayStartedEvent(
        event_time=_INSTANT,
        start_time=_INSTANT,
        end_time=_INSTANT,
        as_of=datetime(2024, 1, 10, tzinfo=UTC),
        instrument_count=1,
    )
    finished = ReplayFinishedEvent(
        event_time=_INSTANT,
        started_at=_INSTANT,
        finished_at=_INSTANT,
        event_count=5,
        bar_count=1,
        instrument_count=1,
    )
    return (started, "market_session", "corporate_action", "market_bar", finished)


def test_noop_implements_research_policy_interface() -> None:
    policy = NoOpBacktestPolicy()
    assert isinstance(policy, ResearchPolicy)
    assert isinstance(EventCountingResearchPolicy(), ResearchPolicy)
    assert NoOpBacktestPolicy is EventCountingResearchPolicy
    assert EventCountingBacktestPolicy is EventCountingResearchPolicy


def test_registry_accepts_noop_and_rejects_unknown() -> None:
    assert "noop" in registered_policy_names()
    assert "event_counting" in registered_policy_names()
    loaded = get_research_policy("noop")
    assert loaded.name == "noop"
    with pytest.raises(BacktestError) as exc:
        get_research_policy("momentum")
    assert exc.value.code == BacktestErrorCode.INVALID_POLICY


def test_policy_config_must_be_json_object() -> None:
    assert normalize_policy_config(None) == {}
    assert normalize_policy_config({"note": "audit"}) == {"note": "audit"}
    with pytest.raises(BacktestError):
        normalize_policy_config({"when": datetime.now(tz=UTC)})  # type: ignore[arg-type]
    with pytest.raises(BacktestError):
        BacktestRequest(replay_id="abc", policy_config={"side": "buy"})


def test_policy_output_hash_is_stable_and_changes_with_observation() -> None:
    policy = EventCountingResearchPolicy(name="event_counting")
    for event in _events():
        policy.observe(event)
    first = policy.finalize()
    again = EventCountingResearchPolicy(name="event_counting")
    for event in _events():
        again.observe(event)
    second = again.finalize()
    assert first.policy_output_hash == second.policy_output_hash
    assert hash_policy_output(first) == first.policy_output_hash
    other = EventCountingResearchPolicy(name="event_counting")
    for event in (*_events(), "market_bar"):
        other.observe(event)
    changed = other.finalize()
    assert changed.policy_output_hash != first.policy_output_hash


def test_backtest_hash_changes_when_policy_config_changes() -> None:
    left = execute_backtest(_events(), _request(), stream_hash=_DIGEST)
    right = execute_backtest(
        _events(),
        _request(policy_config={"note": "window-a"}),
        stream_hash=_DIGEST,
    )
    assert left.summary.backtest_hash != right.summary.backtest_hash
    assert left.summary.policy_output_hash != ""
    assert right.request.policy_config == {"note": "window-a"}


def test_observations_do_not_contain_operative_words() -> None:
    policy = get_research_policy("event_counting")
    for event in _events():
        policy.observe(event)
    output = policy.finalize()
    assert output.observations
    for item in output.observations:
        assert item.kind in ALLOWED_OBSERVATION_KINDS
        blob = json.dumps(item.as_mapping())
        assert contains_operative_language(blob) is False
        for token in FORBIDDEN_OPERATIVE_TOKENS:
            assert token not in item.kind
    with pytest.raises(BacktestError):
        ResearchObservation(
            observation_time=_INSTANT,
            event_time=_INSTANT,
            kind="event_seen",
            message="buy this instrument",
            severity="info",
        )


def test_no_orders_signals_trades_or_portfolio() -> None:
    result = execute_backtest(_events(), _request(), stream_hash=_DIGEST)
    assert result.orders == ()
    assert result.fills == ()
    assert result.signals == ()
    assert result.policy_output is not None
    findings = detect_trading_constructs(event_kinds=tuple(EVENT_PRIORITY))
    assert findings == ()
    names = set(Base.metadata.tables)
    assert names.isdisjoint(FORBIDDEN_TABLE_NAMES)
    assert names.isdisjoint({"portfolio", "positions"})


def test_policy_output_artifact_is_written(tmp_path: Path) -> None:
    result = execute_backtest(
        _events(),
        _request(policy_name="event_counting"),
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
    payload = json.loads((tmp_path / "bt" / "policy_output.json").read_text())
    assert payload["policy_name"] == "event_counting"
    assert payload["policy_output_hash"] == written.summary.policy_output_hash
    assert "DATABASE_URL" not in json.dumps(payload)


def test_diff_detects_policy_config_change(tmp_path: Path) -> None:
    left = execute_backtest(_events(), _request(), stream_hash=_DIGEST)
    right = execute_backtest(
        _events(),
        _request(policy_config={"note": "b"}),
        stream_hash=_DIGEST,
    )
    left_written = write_backtest_artifacts(
        left,
        tmp_path / "left",
        created_at=datetime(2024, 1, 10, tzinfo=UTC),
        git_commit="deadbeef",
        resolve_git=False,
    )
    right_written = write_backtest_artifacts(
        right,
        tmp_path / "right",
        created_at=datetime(2024, 1, 10, tzinfo=UTC),
        git_commit="deadbeef",
        resolve_git=False,
    )
    assert left_written.manifest is not None
    assert right_written.manifest is not None
    diff = diff_backtest_runs(left_written.manifest, right_written.manifest)
    assert diff.verdict == BacktestRunDiffVerdict.DIFFERENT.value
    assert "policy_config" in {item.field for item in diff.items}
