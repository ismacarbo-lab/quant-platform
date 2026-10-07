"""Observation reports and policy-output integrity without Docker."""

from __future__ import annotations

import importlib.util
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from quant_platform.backtest.artifacts import write_backtest_artifacts
from quant_platform.backtest.engine import execute_backtest
from quant_platform.backtest.integrity import verify_backtest_artifacts
from quant_platform.backtest.integrity_types import BacktestIntegrityCode
from quant_platform.backtest.observation_reports import build_observation_report
from quant_platform.backtest.observations import (
    PolicyRunOutput,
    ResearchObservation,
    ResearchObservationSummary,
    hash_policy_output,
    hash_policy_output_mapping,
)
from quant_platform.backtest.policy_output_integrity import (
    compare_policy_outputs,
    verify_policy_output,
    verify_policy_output_mapping,
)
from quant_platform.backtest.policy_output_types import (
    PolicyOutputComparisonVerdict,
    PolicyOutputIntegrityCode,
)
from quant_platform.backtest.readiness import (
    BacktestUsabilityCode,
    build_backtest_usability_report,
)
from quant_platform.backtest.results import hash_backtest_mapping
from quant_platform.backtest.types import BacktestRequest, BacktestRunCatalogEntry
from quant_platform.research.snapshots import hash_manifest_mapping
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
_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


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


def _write_run(directory: Path, *, policy_name: str = "noop"):
    result = execute_backtest(
        _events(), _request(policy_name=policy_name), stream_hash=_DIGEST
    )
    return write_backtest_artifacts(
        result,
        directory,
        created_at=datetime(2024, 1, 10, tzinfo=UTC),
        git_commit="deadbeef",
        resolve_git=False,
    )


def _load_json(path: Path) -> dict[str, object]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return dict(loaded)


def _dump_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def _codes(report) -> set[str]:
    return {item.code for item in report.issues}


def _empty_payload() -> dict[str, object]:
    return {
        "kind": "research_policy_output",
        "format_version": 1,
        "policy_name": "noop",
        "policy_config": {},
        "policy_output_hash": _DIGEST,
        "summary": {
            "observation_count": 0,
            "event_count": 0,
            "market_event_count": 0,
            "session_event_count": 0,
            "corporate_action_event_count": 0,
            "warning_count": 0,
            "error_count": 0,
            "counts_by_kind": {},
        },
        "observations": [],
    }


def _observation(
    *,
    kind: str = "event_seen",
    message: str = "replay started",
    severity: str = "info",
    symbol: str | None = None,
) -> ResearchObservation:
    return ResearchObservation(
        observation_time=_INSTANT,
        event_time=_INSTANT,
        kind=kind,
        message=message,
        severity=severity,
        symbol=symbol,
        instrument_id=None,
        metadata={},
    )


def _output(
    observations: tuple[ResearchObservation, ...],
    *,
    policy_name: str = "noop",
) -> PolicyRunOutput:
    counts: dict[str, int] = {}
    for item in observations:
        counts[item.kind] = counts.get(item.kind, 0) + 1
    summary = ResearchObservationSummary(
        observation_count=len(observations),
        event_count=len(observations),
        market_event_count=0,
        session_event_count=0,
        corporate_action_event_count=0,
        warning_count=sum(1 for item in observations if item.severity == "warning"),
        error_count=sum(1 for item in observations if item.severity == "error"),
        counts_by_kind=dict(sorted(counts.items())),
    )
    draft = PolicyRunOutput(
        policy_name=policy_name,
        policy_config={},
        observations=observations,
        summary=summary,
        policy_output_hash="",
    )
    return replace(draft, policy_output_hash=hash_policy_output(draft))


def _entry_from_written(written, *, backtest_hash: str | None = None):
    manifest = written.manifest
    assert manifest is not None
    values: dict[str, object] = {
        "backtest_id": str(manifest.backtest_id),
        "replay_id": manifest.replay_id,
        "stream_hash": manifest.stream_hash,
        "backtest_hash": backtest_hash or manifest.backtest_hash,
        "manifest_hash": manifest.manifest_hash,
        "policy_name": manifest.policy_name,
        "policy_config": dict(manifest.policy_config),
        "policy_output_hash": manifest.policy_output_hash,
        "package_version": manifest.package_version,
        "git_commit": manifest.git_commit,
        "created_at": datetime(2024, 1, 10, tzinfo=UTC),
        "event_count": 5,
        "market_event_count": 1,
        "session_event_count": 1,
        "corporate_action_event_count": 1,
        "warning_count": 0,
        "error_count": 0,
        "is_reproducible": True,
        "is_usable": True,
        "request": {},
        "summary": {},
        "artifacts": (
            {"name": "summary", "path": "summary.json", "kind": "json"},
            {"name": "manifest", "path": "manifest.json", "kind": "json"},
            {"name": "policy_output", "path": "policy_output.json", "kind": "json"},
        ),
        "notes": None,
        "registered_at": datetime(2024, 1, 10, tzinfo=UTC),
    }
    return BacktestRunCatalogEntry(**values)  # type: ignore[arg-type]


def _load_script(filename: str):
    path = _SCRIPTS / filename
    spec = importlib.util.spec_from_file_location(filename.replace("-", "_"), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_empty_observation_report() -> None:
    report = build_observation_report(_empty_payload())
    assert report.observation_count == 0
    assert report.kinds == ()
    assert report.severities == ()
    assert report.first_observation is None
    assert report.last_observation is None
    assert "empty_observations" in {item.code for item in report.issues}


def test_observation_report_by_kind_and_severity() -> None:
    output = _output(
        (
            _observation(kind="event_seen", message="replay started"),
            _observation(kind="session_seen", message="market session seen"),
            _observation(
                kind="corporate_action_seen",
                message="corporate action seen",
                symbol="FIXT",
            ),
            _observation(
                kind="unknown_event",
                message="unrecognized replay event kind",
                severity="warning",
            ),
        )
    )
    report = build_observation_report(output)
    kinds = {item.kind: item.count for item in report.kinds}
    assert kinds["event_seen"] == 1
    assert kinds["session_seen"] == 1
    assert kinds["corporate_action_seen"] == 1
    assert report.session_count == 1
    assert report.corporate_action_count == 1
    assert report.unknown_event_count == 1
    severities = {item.severity: item.count for item in report.severities}
    assert severities["info"] == 3
    assert severities["warning"] == 1
    assert report.warning_count == 1
    assert report.instruments[0].symbol == "FIXT"


def test_policy_output_hash_matches(tmp_path: Path) -> None:
    written = _write_run(tmp_path / "ok", policy_name="event_counting")
    report = verify_policy_output(tmp_path / "ok")
    assert report.ok is True
    assert report.status == "ok"
    assert report.recomputed_hash == written.summary.policy_output_hash
    assert report.stored_hash == written.summary.policy_output_hash


def test_policy_output_hash_mismatch(tmp_path: Path) -> None:
    _write_run(tmp_path / "run")
    path = tmp_path / "run" / "policy_output.json"
    payload = _load_json(path)
    payload["policy_output_hash"] = "sha256:" + ("b" * 64)
    _dump_json(path, payload)
    report = verify_policy_output(tmp_path / "run")
    assert report.ok is False
    assert PolicyOutputIntegrityCode.POLICY_OUTPUT_HASH_MISMATCH.value in _codes(report)


def test_forbidden_language_detected() -> None:
    payload = _empty_payload()
    payload["observations"] = [
        {
            "observation_time": "2024-01-03T00:00:00.000000Z",
            "event_time": "2024-01-03T00:00:00.000000Z",
            "kind": "policy_note",
            "message": "buy this instrument",
            "severity": "info",
            "instrument_id": None,
            "symbol": None,
            "metadata": {},
        }
    ]
    summary = payload["summary"]
    assert isinstance(summary, dict)
    summary["observation_count"] = 1
    summary["counts_by_kind"] = {"policy_note": 1}
    report = verify_policy_output_mapping(payload)
    assert report.ok is False
    assert PolicyOutputIntegrityCode.FORBIDDEN_OPERATIONAL_LANGUAGE.value in _codes(
        report
    )


def test_invalid_kind_and_severity_detected() -> None:
    payload = _empty_payload()
    payload["observations"] = [
        {
            "observation_time": "2024-01-03T00:00:00.000000Z",
            "event_time": "2024-01-03T00:00:00.000000Z",
            "kind": "not_a_research_kind",
            "message": "descriptive note",
            "severity": "critical",
            "instrument_id": None,
            "symbol": None,
            "metadata": {},
        }
    ]
    summary = payload["summary"]
    assert isinstance(summary, dict)
    summary["observation_count"] = 1
    summary["counts_by_kind"] = {"not_a_research_kind": 1}
    report = verify_policy_output_mapping(payload)
    assert report.ok is False
    assert PolicyOutputIntegrityCode.INVALID_OBSERVATION_KIND.value in _codes(report)
    assert PolicyOutputIntegrityCode.INVALID_OBSERVATION_SEVERITY.value in _codes(
        report
    )


def test_naive_timestamp_rejected() -> None:
    payload = _empty_payload()
    payload["observations"] = [
        {
            "observation_time": "2024-01-03T00:00:00",
            "event_time": "2024-01-03T00:00:00",
            "kind": "event_seen",
            "message": "replay started",
            "severity": "info",
            "instrument_id": None,
            "symbol": None,
            "metadata": {},
        }
    ]
    summary = payload["summary"]
    assert isinstance(summary, dict)
    summary["observation_count"] = 1
    summary["counts_by_kind"] = {"event_seen": 1}
    report = verify_policy_output_mapping(payload)
    assert report.ok is False
    assert PolicyOutputIntegrityCode.TIMESTAMP_NOT_UTC.value in _codes(report)


def test_compare_identical_same_counts_and_different() -> None:
    left = _output((_observation(message="replay started"),))
    same_counts = _output((_observation(message="replay finished"),))
    different = _output(
        (
            _observation(message="replay started"),
            _observation(
                kind="unknown_event",
                message="unrecognized replay event kind",
                severity="warning",
            ),
        )
    )
    identical = compare_policy_outputs(left, left)
    assert identical.verdict == PolicyOutputComparisonVerdict.IDENTICAL.value
    assert identical.identical is True
    counted = compare_policy_outputs(left, same_counts)
    assert counted.verdict == PolicyOutputComparisonVerdict.SAME_COUNTS.value
    assert counted.same_observation_count is True
    assert counted.same_policy_output_hash is False
    changed = compare_policy_outputs(left, different)
    assert changed.verdict == PolicyOutputComparisonVerdict.DIFFERENT.value
    assert changed.same_warning_count is False


def test_backtest_integrity_fails_when_policy_output_fails(tmp_path: Path) -> None:
    _write_run(tmp_path / "run")
    path = tmp_path / "run" / "policy_output.json"
    payload = _load_json(path)
    payload["policy_output_hash"] = "sha256:" + ("b" * 64)
    _dump_json(path, payload)
    report = verify_backtest_artifacts(tmp_path / "run")
    assert report.ok is False
    assert report.policy_output_ok is False
    assert BacktestIntegrityCode.POLICY_OUTPUT_HASH_MISMATCH.value in _codes(report)


def test_usability_fails_when_policy_output_has_operative_language(
    tmp_path: Path,
) -> None:
    written = _write_run(tmp_path / "run", policy_name="event_counting")
    path = tmp_path / "run" / "policy_output.json"
    payload = _load_json(path)
    observations = payload.get("observations")
    assert isinstance(observations, list) and observations
    first = observations[0]
    assert isinstance(first, dict)
    first["message"] = "buy this instrument"
    digest = hash_policy_output_mapping(payload)
    payload["policy_output_hash"] = digest
    _dump_json(path, payload)
    summary_path = tmp_path / "run" / "summary.json"
    manifest_path = tmp_path / "run" / "manifest.json"
    summary = _load_json(summary_path)
    summary["policy_output_hash"] = digest
    summary["backtest_hash"] = hash_backtest_mapping(summary)
    _dump_json(summary_path, summary)
    manifest = _load_json(manifest_path)
    manifest["policy_output_hash"] = digest
    manifest["backtest_hash"] = summary["backtest_hash"]
    nested = manifest.get("summary")
    if isinstance(nested, dict):
        nested["policy_output_hash"] = digest
        nested["backtest_hash"] = summary["backtest_hash"]
        manifest["summary"] = nested
    manifest["manifest_hash"] = hash_manifest_mapping(manifest)
    _dump_json(manifest_path, manifest)
    integrity = verify_backtest_artifacts(tmp_path / "run")
    assert integrity.ok is False
    assert BacktestIntegrityCode.FORBIDDEN_OPERATIONAL_LANGUAGE.value in _codes(
        integrity
    )
    entry = _entry_from_written(
        written,
        backtest_hash=str(summary["backtest_hash"]),
    )
    entry = replace(
        entry,
        manifest_hash=str(manifest["manifest_hash"]),
        policy_output_hash=digest,
    )
    usability = build_backtest_usability_report(
        backtest_id=entry.backtest_id,
        entry=entry,
        integrity=integrity,
        replay_registered=True,
        research_mode=True,
        run_root=tmp_path / "run",
    )
    assert usability.usable_result is False
    assert usability.gate.policy_output_ok is False
    assert BacktestUsabilityCode.POLICY_OUTPUT_INVALID.value in {
        item.code for item in usability.issues
    }


def test_no_trading_modules() -> None:
    findings = detect_trading_constructs(event_kinds=tuple(EVENT_PRIORITY))
    assert findings == ()
    names = set(Base.metadata.tables)
    assert names.isdisjoint(FORBIDDEN_TABLE_NAMES)
    assert names.isdisjoint({"portfolio", "positions", "orders", "fills"})
    root = Path(__file__).resolve().parents[2] / "src" / "quant_platform"
    # Research dry-run packages must not grow trading modules; the simulated
    # paper layer lives in its own packages (ADR 0005).
    research_roots = ("backtest", "simulation", "research", "data", "release")
    forbidden = {"strategy", "signal", "order", "portfolio", "broker", "live"}
    found = {
        path.stem
        for package in research_roots
        for path in (root / package).rglob("*.py")
        if path.stem in forbidden
    }
    assert found == set()
    assert not (root / "live").exists()


def test_policy_output_scripts_parse_args() -> None:
    for name in (
        "report-policy-output.py",
        "verify-policy-output.py",
        "verify-backtest-run.py",
    ):
        script = _load_script(name)
        with pytest.raises(SystemExit) as exc:
            script.main(["--help"])
        assert exc.value.code == 0
