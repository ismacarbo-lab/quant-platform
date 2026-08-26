"""Backtest artifact integrity, comparison, and usability without Docker."""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from quant_platform.backtest.artifacts import write_backtest_artifacts
from quant_platform.backtest.compare import BacktestRunDiffVerdict, diff_backtest_runs
from quant_platform.backtest.engine import execute_backtest
from quant_platform.backtest.integrity import (
    resolve_backtest_run_directory,
    verify_backtest_artifacts,
)
from quant_platform.backtest.integrity_types import (
    BacktestArtifactVerificationIssue,
    BacktestArtifactVerificationReport,
    BacktestIntegrityCode,
)
from quant_platform.backtest.readiness import (
    BacktestUsabilityCode,
    build_backtest_usability_report,
)
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
_OTHER = "sha256:" + ("b" * 64)
_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
_INSTANT = datetime(2024, 1, 3, tzinfo=UTC)


def _request() -> BacktestRequest:
    return BacktestRequest(
        replay_id="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
        deterministic_id=True,
    )


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


def _write_run(directory: Path):
    result = execute_backtest(_events(), _request(), stream_hash=_DIGEST)
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


def _load_script(filename: str):
    path = _SCRIPTS / filename
    spec = importlib.util.spec_from_file_location(filename.replace("-", "_"), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _entry(**overrides: object) -> BacktestRunCatalogEntry:
    values: dict[str, object] = {
        "backtest_id": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
        "replay_id": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
        "stream_hash": _DIGEST,
        "backtest_hash": _OTHER,
        "manifest_hash": _DIGEST,
        "policy_name": "noop",
        "package_version": "0.1.0",
        "git_commit": "deadbeef",
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
        ),
        "notes": None,
        "registered_at": datetime(2024, 1, 10, tzinfo=UTC),
    }
    values.update(overrides)
    return BacktestRunCatalogEntry(**values)  # type: ignore[arg-type]


def test_valid_manifest_and_summary_pass(tmp_path: Path) -> None:
    written = _write_run(tmp_path / "ok")
    report = verify_backtest_artifacts(tmp_path / "ok")
    assert report.ok is True
    assert report.error_count == 0
    assert report.recomputed_backtest_hash == written.summary.backtest_hash
    assert report.recomputed_manifest_hash == written.manifest.manifest_hash
    assert "DATABASE_URL" not in json.dumps(report.as_mapping())


def test_missing_manifest(tmp_path: Path) -> None:
    _write_run(tmp_path / "run")
    (tmp_path / "run" / "manifest.json").unlink()
    report = verify_backtest_artifacts(tmp_path / "run")
    assert report.ok is False
    assert BacktestIntegrityCode.MISSING_MANIFEST.value in _codes(report)


def test_missing_summary(tmp_path: Path) -> None:
    _write_run(tmp_path / "run")
    (tmp_path / "run" / "summary.json").unlink()
    report = verify_backtest_artifacts(tmp_path / "run")
    assert report.ok is False
    assert BacktestIntegrityCode.MISSING_SUMMARY.value in _codes(report)


def test_absolute_path_rejected(tmp_path: Path) -> None:
    _write_run(tmp_path / "run")
    manifest_path = tmp_path / "run" / "manifest.json"
    payload = _load_json(manifest_path)
    payload["artifacts"] = [
        {"name": "summary", "path": "/abs/summary.json", "kind": "json"},
        {"name": "manifest", "path": "manifest.json", "kind": "json"},
    ]
    payload["manifest_hash"] = hash_manifest_mapping(payload)
    _dump_json(manifest_path, payload)
    report = verify_backtest_artifacts(tmp_path / "run")
    assert report.ok is False
    assert BacktestIntegrityCode.ABSOLUTE_PATH.value in _codes(report)


def test_path_traversal_rejected(tmp_path: Path) -> None:
    _write_run(tmp_path / "run")
    manifest_path = tmp_path / "run" / "manifest.json"
    payload = _load_json(manifest_path)
    payload["artifacts"] = [
        {"name": "summary", "path": "../secret.json", "kind": "json"},
        {"name": "manifest", "path": "manifest.json", "kind": "json"},
    ]
    payload["manifest_hash"] = hash_manifest_mapping(payload)
    _dump_json(manifest_path, payload)
    report = verify_backtest_artifacts(tmp_path / "run")
    assert report.ok is False
    assert BacktestIntegrityCode.PATH_ESCAPE.value in _codes(report)


def test_secret_like_value_rejected(tmp_path: Path) -> None:
    _write_run(tmp_path / "run")
    manifest_path = tmp_path / "run" / "manifest.json"
    payload = _load_json(manifest_path)
    payload["notes"] = "DATABASE_URL=postgresql://quant:secret@localhost/db"
    payload["manifest_hash"] = hash_manifest_mapping(payload)
    _dump_json(manifest_path, payload)
    report = verify_backtest_artifacts(tmp_path / "run")
    assert report.ok is False
    assert BacktestIntegrityCode.SECRET_LIKE_VALUE.value in _codes(report)


def test_manifest_hash_mismatch(tmp_path: Path) -> None:
    _write_run(tmp_path / "run")
    manifest_path = tmp_path / "run" / "manifest.json"
    payload = _load_json(manifest_path)
    payload["notes"] = "tampered"
    _dump_json(manifest_path, payload)
    report = verify_backtest_artifacts(tmp_path / "run")
    assert report.ok is False
    assert BacktestIntegrityCode.MANIFEST_HASH_MISMATCH.value in _codes(report)


def test_backtest_hash_mismatch(tmp_path: Path) -> None:
    _write_run(tmp_path / "run")
    summary_path = tmp_path / "run" / "summary.json"
    manifest_path = tmp_path / "run" / "manifest.json"
    summary = _load_json(summary_path)
    manifest = _load_json(manifest_path)
    summary["backtest_hash"] = _OTHER
    nested = manifest.get("summary")
    assert isinstance(nested, dict)
    nested["backtest_hash"] = _OTHER
    manifest["summary"] = nested
    manifest["backtest_hash"] = _OTHER
    manifest["manifest_hash"] = hash_manifest_mapping(manifest)
    _dump_json(summary_path, summary)
    _dump_json(manifest_path, manifest)
    report = verify_backtest_artifacts(tmp_path / "run")
    assert report.ok is False
    assert BacktestIntegrityCode.BACKTEST_HASH_MISMATCH.value in _codes(report)


def test_diff_identical_same_result_and_different(tmp_path: Path) -> None:
    request = _request()
    left_result = execute_backtest(_events(), request, stream_hash=_DIGEST)
    longer = execute_backtest((*_events(), "market_bar"), request, stream_hash=_DIGEST)
    left = write_backtest_artifacts(
        left_result,
        tmp_path / "left",
        created_at=datetime(2024, 1, 10, tzinfo=UTC),
        git_commit="deadbeef",
        resolve_git=False,
    )
    same_result = write_backtest_artifacts(
        left_result,
        tmp_path / "same",
        created_at=datetime(2024, 6, 1, tzinfo=UTC),
        git_commit="deadbeef",
        resolve_git=False,
    )
    right = write_backtest_artifacts(
        longer,
        tmp_path / "right",
        created_at=datetime(2024, 1, 10, tzinfo=UTC),
        git_commit="deadbeef",
        resolve_git=False,
    )
    assert left.manifest is not None
    assert same_result.manifest is not None
    assert right.manifest is not None
    identical = diff_backtest_runs(left.manifest, left.manifest)
    assert identical.verdict == BacktestRunDiffVerdict.IDENTICAL.value
    assert identical.identical is True
    same = diff_backtest_runs(left.manifest, same_result.manifest)
    assert same.verdict == BacktestRunDiffVerdict.SAME_RESULT.value
    assert same.same_backtest_hash is True
    assert same.same_manifest_hash is False
    different = diff_backtest_runs(left.manifest, right.manifest)
    assert different.verdict == BacktestRunDiffVerdict.DIFFERENT.value
    assert different.same_backtest_hash is False


def test_usability_ok_and_failures() -> None:
    entry = _entry()
    integrity = BacktestArtifactVerificationReport(
        run_root="run",
        backtest_id=entry.backtest_id,
        replay_id=entry.replay_id,
        ok=True,
        error_count=0,
        warning_count=0,
        info_count=0,
        issues=(),
        artifacts=(),
        stream_hash=entry.stream_hash,
        backtest_hash=entry.backtest_hash,
        recomputed_backtest_hash=entry.backtest_hash,
        manifest_hash=entry.manifest_hash,
        recomputed_manifest_hash=entry.manifest_hash,
        policy_name="noop",
        event_count=5,
    )
    ok = build_backtest_usability_report(
        backtest_id=entry.backtest_id,
        entry=entry,
        integrity=integrity,
        replay_registered=True,
        research_mode=True,
        run_root="run",
    )
    assert ok.usable_result is True
    missing = build_backtest_usability_report(
        backtest_id=entry.backtest_id,
        entry=entry,
        integrity=None,
        research_mode=True,
        run_root=None,
    )
    assert missing.usable_result is False
    assert BacktestUsabilityCode.ARTIFACT_MISSING.value in {
        item.code for item in missing.issues
    }
    broken_integrity = BacktestArtifactVerificationReport(
        run_root="run",
        backtest_id=entry.backtest_id,
        replay_id=entry.replay_id,
        ok=False,
        error_count=1,
        warning_count=0,
        info_count=0,
        issues=(
            BacktestArtifactVerificationIssue(
                severity="error",
                code=BacktestIntegrityCode.MISSING_SUMMARY.value,
                message="summary.json is missing",
                path="summary.json",
            ),
        ),
        artifacts=(),
        stream_hash=entry.stream_hash,
        backtest_hash=entry.backtest_hash,
        recomputed_backtest_hash=None,
        manifest_hash=entry.manifest_hash,
        recomputed_manifest_hash=entry.manifest_hash,
        policy_name="noop",
        event_count=None,
    )
    artifact_fail = build_backtest_usability_report(
        backtest_id=entry.backtest_id,
        entry=entry,
        integrity=broken_integrity,
        research_mode=True,
        run_root="run",
    )
    assert artifact_fail.usable_result is False
    assert artifact_fail.gate.artifacts_ok is False
    errors = build_backtest_usability_report(
        backtest_id=entry.backtest_id,
        entry=_entry(error_count=2, is_usable=False),
        integrity=integrity,
        research_mode=True,
        run_root="run",
    )
    assert errors.usable_result is False
    assert BacktestUsabilityCode.ERRORS_PRESENT.value in {
        item.code for item in errors.issues
    }


def test_no_trading_constructs() -> None:
    findings = detect_trading_constructs(event_kinds=tuple(EVENT_PRIORITY))
    assert findings == ()
    names = set(Base.metadata.tables)
    assert "backtest_runs" in names
    assert names.isdisjoint(FORBIDDEN_TABLE_NAMES)
    assert names.isdisjoint({"portfolio", "positions"})


def test_resolve_backtest_run_directory(tmp_path: Path) -> None:
    written = _write_run(tmp_path / "nested")
    assert written.manifest is not None
    backtest_id = str(written.manifest.backtest_id)
    found = resolve_backtest_run_directory(tmp_path / "nested", backtest_id)
    assert found == tmp_path / "nested"
    parent = resolve_backtest_run_directory(tmp_path, backtest_id)
    assert parent == tmp_path / "nested"


def test_integrity_scripts_parse_args() -> None:
    for name in (
        "verify-backtest-run.py",
        "check-backtest-usability.py",
        "compare-backtest-runs.py",
        "list-backtest-runs.py",
    ):
        script = _load_script(name)
        with pytest.raises(SystemExit) as exc:
            script.main(["--help"])
        assert exc.value.code == 0
