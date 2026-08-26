"""Replay-run comparison and backtest readiness without Docker."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from quant_platform.simulation.constructs import detect_trading_constructs
from quant_platform.simulation.readiness import (
    build_readiness_report,
    readiness_canonical_json,
    readiness_report_json,
    resolve_replay_run_directory,
)
from quant_platform.simulation.readiness_types import ReplayRunReadinessCode
from quant_platform.simulation.run_compare import diff_replay_runs
from quant_platform.simulation.run_integrity import (
    ReplayRunIntegrityIssue,
    ReplayRunIntegrityReport,
)
from quant_platform.simulation.run_types import (
    ReplayRunCatalogEntry,
    ReplayRunManifest,
    default_replay_run_artifacts,
)

_DIGEST = "sha256:" + ("a" * 64)
_OTHER = "sha256:" + ("b" * 64)
_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _manifest(**overrides: object) -> ReplayRunManifest:
    values: dict[str, object] = {
        "replay_id": UUID("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"),
        "created_at": datetime(2024, 1, 10, tzinfo=UTC),
        "package_version": "0.1.0",
        "git_commit": "deadbeef",
        "source_type": "database",
        "dataset_snapshot_id": None,
        "dataset_content_hash": _DIGEST,
        "stream_hash": _DIGEST,
        "event_count": 3,
        "event_counts_by_type": {
            "market_bar": 1,
            "replay_finished": 1,
            "replay_started": 1,
        },
        "pre_known_event_count": 0,
        "boundary_ok": True,
        "warning_count": 0,
        "error_count": 0,
        "first_event_time": datetime(2024, 1, 3, tzinfo=UTC),
        "last_event_time": datetime(2024, 1, 3, tzinfo=UTC),
        "first_market_event_time": datetime(2024, 1, 3, tzinfo=UTC),
        "last_market_event_time": datetime(2024, 1, 3, tzinfo=UTC),
        "request": {"symbols": ["FICT"]},
        "audit_summary": {
            "ok": True,
            "boundary_ok": True,
            "error_count": 0,
            "counts_by_kind": {
                "market_bar": 1,
                "replay_finished": 1,
                "replay_started": 1,
            },
        },
        "artifacts": default_replay_run_artifacts(),
        "notes": None,
        "manifest_hash": _OTHER,
    }
    values.update(overrides)
    return ReplayRunManifest(**values)  # type: ignore[arg-type]


def _entry(**overrides: object) -> ReplayRunCatalogEntry:
    values: dict[str, object] = {
        "replay_id": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
        "stream_hash": _DIGEST,
        "manifest_hash": _OTHER,
        "source_type": "database",
        "dataset_snapshot_id": None,
        "dataset_content_hash": _DIGEST,
        "package_version": "0.1.0",
        "git_commit": "deadbeef",
        "created_at": datetime(2024, 1, 10, tzinfo=UTC),
        "as_of": datetime(2024, 1, 10, tzinfo=UTC),
        "start_time": datetime(2024, 1, 1, tzinfo=UTC),
        "end_time": datetime(2024, 1, 5, tzinfo=UTC),
        "event_count": 3,
        "market_event_count": 1,
        "session_event_count": 0,
        "corporate_action_event_count": 0,
        "pre_known_event_count": 0,
        "warning_count": 0,
        "error_count": 0,
        "boundary_ok": True,
        "is_reproducible": True,
        "is_usable": True,
        "request": {"symbols": ["FICT"]},
        "audit_summary": {
            "ok": True,
            "counts_by_kind": {
                "market_bar": 1,
                "replay_finished": 1,
                "replay_started": 1,
            },
        },
        "artifacts": tuple(
            item.as_mapping() for item in default_replay_run_artifacts()
        ),
        "notes": None,
        "registered_at": datetime(2024, 1, 10, tzinfo=UTC),
    }
    values.update(overrides)
    return ReplayRunCatalogEntry(**values)  # type: ignore[arg-type]


def _ok_integrity(replay_id: str) -> ReplayRunIntegrityReport:
    return ReplayRunIntegrityReport(
        run_root="run",
        replay_id=replay_id,
        ok=True,
        error_count=0,
        warning_count=0,
        info_count=0,
        issues=(),
        artifacts=(),
        stream_hash=_DIGEST,
        recomputed_stream_hash=_DIGEST,
        manifest_hash=_OTHER,
        recomputed_manifest_hash=_OTHER,
        event_count=3,
        jsonl_event_count=3,
    )


def _broken_integrity(
    replay_id: str, *, code: str, message: str, path: str | None = None
) -> ReplayRunIntegrityReport:
    issue = ReplayRunIntegrityIssue(
        severity="error",
        code=code,
        message=message,
        path=path,
    )
    return ReplayRunIntegrityReport(
        run_root="run",
        replay_id=replay_id,
        ok=False,
        error_count=1,
        warning_count=0,
        info_count=0,
        issues=(issue,),
        artifacts=(),
        stream_hash=_DIGEST,
        recomputed_stream_hash=_DIGEST,
        manifest_hash=_OTHER,
        recomputed_manifest_hash=_OTHER,
        event_count=3,
        jsonl_event_count=None,
    )


def _load_script(filename: str):
    path = _SCRIPTS / filename
    spec = importlib.util.spec_from_file_location(filename.replace("-", "_"), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_diff_replay_runs_identical() -> None:
    left = _manifest()
    diff = diff_replay_runs(left, left)
    assert diff.identical is True
    assert diff.same_stream_hash is True
    assert diff.same_manifest_hash is True
    assert diff.verdict == "identical"
    assert diff.items == ()


def test_diff_replay_runs_stream_hash() -> None:
    left = _manifest()
    right = _manifest(stream_hash=_OTHER, replay_id=uuid4())
    diff = diff_replay_runs(left, right)
    assert diff.same_stream_hash is False
    assert diff.verdict == "different"
    fields = {item.field for item in diff.items}
    assert "stream_hash" in fields
    assert any(
        item.code == ReplayRunReadinessCode.STREAM_HASH_DIFF.value
        for item in diff.items
    )


def test_diff_replay_runs_event_counts() -> None:
    left = _manifest()
    right = _manifest(
        event_count=4,
        event_counts_by_type={
            "market_bar": 2,
            "replay_finished": 1,
            "replay_started": 1,
        },
    )
    diff = diff_replay_runs(left, right)
    assert diff.same_stream_hash is True
    assert diff.verdict == "same_stream"
    fields = {item.field for item in diff.items}
    assert "event_count" in fields
    assert "event_counts_by_type" in fields
    assert "market_event_count" in fields


def test_readiness_ok() -> None:
    entry = _entry()
    report = build_readiness_report(
        replay_id=entry.replay_id,
        entry=entry,
        integrity=_ok_integrity(entry.replay_id),
        constructs=(),
        research_mode=True,
        run_root="run",
    )
    assert report.ready_for_backtest is True
    assert report.gate.artifacts_ok is True
    assert report.error_count == 0
    assert "DATABASE_URL" not in readiness_report_json(report)


def test_readiness_fails_boundary() -> None:
    entry = _entry(boundary_ok=False, is_usable=False)
    report = build_readiness_report(
        replay_id=entry.replay_id,
        entry=entry,
        integrity=_ok_integrity(entry.replay_id),
        run_root="run",
    )
    assert report.ready_for_backtest is False
    codes = {item.code for item in report.issues}
    assert ReplayRunReadinessCode.BOUNDARY_NOT_OK.value in codes


def test_readiness_fails_artifact_missing() -> None:
    entry = _entry()
    integrity = _broken_integrity(
        entry.replay_id,
        code="missing_artifact",
        message="events.jsonl is missing",
        path="events.jsonl",
    )
    report = build_readiness_report(
        replay_id=entry.replay_id,
        entry=entry,
        integrity=integrity,
        run_root="run",
    )
    assert report.ready_for_backtest is False
    codes = {item.code for item in report.issues}
    assert ReplayRunReadinessCode.ARTIFACT_MISSING.value in codes


def test_readiness_fails_audit_errors() -> None:
    entry = _entry(error_count=2, is_usable=False)
    report = build_readiness_report(
        replay_id=entry.replay_id,
        entry=entry,
        integrity=_ok_integrity(entry.replay_id),
        run_root="run",
    )
    assert report.ready_for_backtest is False
    codes = {item.code for item in report.issues}
    assert ReplayRunReadinessCode.AUDIT_ERRORS_PRESENT.value in codes


def test_readiness_fails_trading_construct_fixture() -> None:
    findings = detect_trading_constructs(
        scan_packages=False,
        scan_tables=False,
        event_kinds=("order_fill",),
    )
    assert findings
    entry = _entry()
    report = build_readiness_report(
        replay_id=entry.replay_id,
        entry=entry,
        integrity=_ok_integrity(entry.replay_id),
        constructs=findings,
        run_root="run",
    )
    assert report.ready_for_backtest is False
    codes = {item.code for item in report.issues}
    assert ReplayRunReadinessCode.TRADING_CONSTRUCT_DETECTED.value in codes


def test_detect_trading_constructs_clean_tree() -> None:
    findings = detect_trading_constructs(
        event_kinds=("replay_started", "market_bar", "replay_finished")
    )
    assert findings == ()


def test_readiness_json_is_stable() -> None:
    entry = _entry()
    report = build_readiness_report(
        replay_id=entry.replay_id,
        entry=entry,
        integrity=_ok_integrity(entry.replay_id),
        run_root="run",
    )
    first = readiness_canonical_json(report)
    second = readiness_canonical_json(report)
    assert first == second
    pretty = readiness_report_json(report)
    assert pretty == readiness_report_json(report)
    assert "DATABASE_URL" not in pretty


def test_resolve_replay_run_directory(tmp_path: Path) -> None:
    run = tmp_path / "nested"
    run.mkdir()
    (run / "manifest.json").write_text(
        '{"replay_id": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"}\n',
        encoding="utf-8",
    )
    found = resolve_replay_run_directory(run, "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")
    assert found == run
    parent = resolve_replay_run_directory(
        tmp_path, "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    )
    assert parent == run


def test_compare_and_readiness_scripts_parse_args() -> None:
    compare = _load_script("compare-replay-runs.py")
    with pytest.raises(SystemExit) as help_exc:
        compare.main(["--help"])
    assert help_exc.value.code == 0
    with pytest.raises(SystemExit) as missing:
        compare.main(["--left", "abc"])
    assert missing.value.code == 2
    readiness = _load_script("check-replay-readiness.py")
    with pytest.raises(SystemExit) as ready_help:
        readiness.main(["--help"])
    assert ready_help.value.code == 0
    with pytest.raises(SystemExit) as ready_missing:
        readiness.main(["--replay-id", "abc"])
    assert ready_missing.value.code == 2
