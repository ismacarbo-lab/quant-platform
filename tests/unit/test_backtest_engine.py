"""Dry-run backtest engine without Docker. No strategies or trading."""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from quant_platform.backtest.artifacts import write_backtest_artifacts
from quant_platform.backtest.catalog import (
    compare_backtest_runs,
    raise_if_manifest_hash_conflict,
)
from quant_platform.backtest.engine import (
    execute_backtest,
    require_backtest_readiness,
    run_backtest_from_replay_run,
)
from quant_platform.backtest.errors import BacktestError, BacktestErrorCode
from quant_platform.backtest.policy import (
    EventCountingBacktestPolicy,
    NoOpBacktestPolicy,
)
from quant_platform.backtest.results import hash_backtest_result
from quant_platform.backtest.types import (
    BacktestArtifact,
    BacktestManifest,
    BacktestRequest,
    BacktestRunCatalogEntry,
    default_backtest_artifacts,
)
from quant_platform.simulation.constructs import (
    FORBIDDEN_PACKAGE_NAMES,
    FORBIDDEN_TABLE_NAMES,
    detect_trading_constructs,
)
from quant_platform.simulation.events import (
    EVENT_PRIORITY,
    MARKET_BAR_KIND,
    REPLAY_FINISHED_KIND,
    REPLAY_STARTED_KIND,
    ReplayFinishedEvent,
    ReplayStartedEvent,
)
from quant_platform.simulation.readiness import build_readiness_report
from quant_platform.storage.database import Base

_DIGEST = "sha256:" + ("a" * 64)
_OTHER = "sha256:" + ("b" * 64)
_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
_INSTANT = datetime(2024, 1, 3, tzinfo=UTC)


def _request(**overrides: object) -> BacktestRequest:
    values: dict[str, object] = {
        "replay_id": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
        "deterministic_id": True,
        "policy_name": "noop",
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


def _load_script(filename: str):
    path = _SCRIPTS / filename
    spec = importlib.util.spec_from_file_location(filename.replace("-", "_"), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_noop_policy_counts_events_and_emits_no_orders() -> None:
    policy = NoOpBacktestPolicy()
    for event in _events():
        policy.observe(event)
    assert policy.event_count == 5
    assert policy.market_event_count == 1
    assert policy.session_event_count == 1
    assert policy.corporate_action_event_count == 1
    assert policy.started_event_seen is True
    assert policy.finished_event_seen is True
    assert policy.orders == ()
    assert policy.fills == ()
    assert policy.signals == ()
    assert policy.emitted_orders() == ()
    assert policy.warnings == ()
    alias = EventCountingBacktestPolicy()
    alias.observe(MARKET_BAR_KIND)
    assert alias.market_event_count == 1
    assert alias.orders == ()


def test_noop_policy_warns_on_unknown_event_without_orders() -> None:
    policy = NoOpBacktestPolicy()
    policy.observe("order_fill")
    assert policy.event_count == 1
    assert policy.warnings == ("unknown_event:order_fill",)
    assert policy.orders == ()
    assert policy.fills == ()
    assert policy.signals == ()


def test_engine_fails_if_readiness_does_not_pass() -> None:
    report = build_readiness_report(
        replay_id="missing",
        entry=None,
        integrity=None,
        research_mode=True,
        run_root=None,
    )
    assert report.ready_for_backtest is False
    with pytest.raises(BacktestError) as exc:
        require_backtest_readiness(report)
    assert exc.value.code == BacktestErrorCode.NOT_READY


def test_engine_fails_when_app_mode_is_not_research() -> None:
    with pytest.raises(BacktestError) as exc:
        run_backtest_from_replay_run(
            MagicMock(),
            _request(),
            ".",
            research_mode=False,
        )
    assert exc.value.code == BacktestErrorCode.APP_MODE_NOT_RESEARCH


def test_backtest_hash_is_stable_and_changes_with_count() -> None:
    request = _request()
    first = execute_backtest(_events(), request, stream_hash=_DIGEST)
    second = execute_backtest(_events(), request, stream_hash=_DIGEST)
    assert first.summary.backtest_hash == second.summary.backtest_hash
    assert first.summary.backtest_id == second.summary.backtest_id
    assert hash_backtest_result(first) == first.summary.backtest_hash
    longer = execute_backtest(
        (*_events(), "market_bar"),
        request,
        stream_hash=_DIGEST,
    )
    assert longer.summary.backtest_hash != first.summary.backtest_hash
    assert longer.summary.event_count == first.summary.event_count + 1
    random_ids = execute_backtest(
        _events(),
        _request(deterministic_id=False),
        stream_hash=_DIGEST,
    )
    assert random_ids.summary.backtest_hash == first.summary.backtest_hash
    assert random_ids.summary.backtest_id != first.summary.backtest_id


def test_manifest_has_relative_paths_and_no_secrets(tmp_path: Path) -> None:
    result = execute_backtest(_events(), _request(), stream_hash=_DIGEST)
    written = write_backtest_artifacts(
        result,
        tmp_path / "bt",
        created_at=datetime(2024, 1, 10, tzinfo=UTC),
        git_commit="deadbeef",
        resolve_git=False,
    )
    assert written.manifest is not None
    text = (tmp_path / "bt" / "manifest.json").read_text(encoding="utf-8")
    summary = (tmp_path / "bt" / "summary.json").read_text(encoding="utf-8")
    assert "DATABASE_URL" not in text
    assert "DATABASE_URL" not in summary
    assert "postgresql://" not in text.lower()
    payload = json.loads(text)
    for item in payload["artifacts"]:
        path = Path(item["path"])
        assert not path.is_absolute()
        assert ".." not in path.parts
    assert payload["backtest_hash"] == result.summary.backtest_hash
    assert (tmp_path / "bt" / "events.jsonl").exists() is False
    later = write_backtest_artifacts(
        result,
        tmp_path / "later",
        created_at=datetime(2024, 6, 1, tzinfo=UTC),
        git_commit="deadbeef",
        resolve_git=False,
    )
    assert later.manifest is not None
    assert later.manifest.backtest_hash == written.manifest.backtest_hash
    assert later.manifest.manifest_hash != written.manifest.manifest_hash


def test_compare_backtest_runs(tmp_path: Path) -> None:
    request = _request()
    left_result = execute_backtest(_events(), request, stream_hash=_DIGEST)
    right_result = execute_backtest(
        (*_events(), "market_bar"),
        request,
        stream_hash=_DIGEST,
    )
    left = write_backtest_artifacts(
        left_result,
        tmp_path / "left",
        created_at=datetime(2024, 1, 10, tzinfo=UTC),
        git_commit="deadbeef",
        resolve_git=False,
    )
    right = write_backtest_artifacts(
        right_result,
        tmp_path / "right",
        created_at=datetime(2024, 1, 10, tzinfo=UTC),
        git_commit="deadbeef",
        resolve_git=False,
    )
    assert left.manifest is not None and right.manifest is not None
    comparison = compare_backtest_runs(left.manifest, right.manifest)
    assert comparison.same_replay_id is True
    assert comparison.same_policy_name is True
    assert comparison.same_backtest_hash is False
    assert comparison.event_count_delta == 1
    assert "backtest_hash" in comparison.differences
    assert "event_count" in comparison.differences
    same = compare_backtest_runs(left.manifest, left.manifest)
    assert same.same_backtest_hash is True
    assert same.differences == ()


def test_manifest_hash_conflict_helper() -> None:
    manifest = BacktestManifest(
        backtest_id=UUID("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"),
        created_at=datetime(2024, 1, 10, tzinfo=UTC),
        package_version="0.1.0",
        git_commit="deadbeef",
        replay_id="replay-1",
        stream_hash=_DIGEST,
        backtest_hash=_OTHER,
        policy_name="noop",
        policy_config={},
        policy_output_hash=_DIGEST,
        request={"replay_id": "replay-1"},
        summary={"event_count": 1},
        artifacts=default_backtest_artifacts(),
        notes=None,
        manifest_hash=_DIGEST,
    )
    owner = BacktestRunCatalogEntry(
        backtest_id=str(uuid4()),
        replay_id="replay-1",
        stream_hash=_DIGEST,
        backtest_hash=_OTHER,
        manifest_hash=_DIGEST,
        policy_name="noop",
        policy_config={},
        policy_output_hash=_DIGEST,
        package_version="0.1.0",
        git_commit="deadbeef",
        created_at=datetime(2024, 1, 10, tzinfo=UTC),
        event_count=1,
        market_event_count=0,
        session_event_count=0,
        corporate_action_event_count=0,
        warning_count=0,
        error_count=0,
        is_reproducible=True,
        is_usable=True,
        request={},
        summary={},
        artifacts=(),
        notes=None,
        registered_at=datetime(2024, 1, 10, tzinfo=UTC),
    )
    with pytest.raises(BacktestError) as exc:
        raise_if_manifest_hash_conflict(owner, manifest)
    assert exc.value.code == BacktestErrorCode.CATALOG_CONFLICT
    raise_if_manifest_hash_conflict(None, manifest)


def test_no_forbidden_trading_modules_tables_or_event_kinds() -> None:
    import quant_platform

    root = Path(quant_platform.__file__).resolve().parent
    assert (root / "backtest").is_dir()
    for name in FORBIDDEN_PACKAGE_NAMES:
        assert not (root / name).is_dir()
        assert not (root / f"{name}.py").is_file()
    findings = detect_trading_constructs(
        event_kinds=tuple(EVENT_PRIORITY),
    )
    assert findings == ()
    names = set(Base.metadata.tables)
    assert "backtest_runs" in names
    assert names.isdisjoint(FORBIDDEN_TABLE_NAMES)
    for kind in EVENT_PRIORITY:
        lowered = kind.lower()
        assert "order" not in lowered
        assert "fill" not in lowered
        assert "trade" not in lowered
        assert "signal" not in lowered
        assert "position" not in lowered
        assert "portfolio" not in lowered
    assert REPLAY_STARTED_KIND in EVENT_PRIORITY
    assert REPLAY_FINISHED_KIND in EVENT_PRIORITY
    artifact = BacktestArtifact(name="summary", path="summary.json", kind="json")
    assert artifact.path == "summary.json"


def test_backtest_scripts_parse_args() -> None:
    runner = _load_script("run-backtest.py")
    with pytest.raises(SystemExit) as help_exc:
        runner.main(["--help"])
    assert help_exc.value.code == 0
    with pytest.raises(SystemExit) as missing:
        runner.main([])
    assert missing.value.code == 2
    listing = _load_script("list-backtest-runs.py")
    with pytest.raises(SystemExit) as list_help:
        listing.main(["--help"])
    assert list_help.value.code == 0


def test_invalid_policy_name_is_rejected() -> None:
    with pytest.raises(BacktestError) as exc:
        BacktestRequest(replay_id="abc", policy_name="momentum")
    assert exc.value.code == BacktestErrorCode.INVALID_POLICY
