"""Dry-run backtest experiments without Docker. Not a strategy."""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from quant_platform.backtest.errors import BacktestError, BacktestErrorCode
from quant_platform.backtest.experiment_artifacts import (
    write_backtest_experiment_artifacts,
)
from quant_platform.backtest.experiment_catalog import compare_backtest_experiments
from quant_platform.backtest.experiment_integrity import (
    ExperimentIntegrityCode,
    verify_backtest_experiment_artifacts,
)
from quant_platform.backtest.experiment_types import (
    EXPERIMENT_VERDICT_DIFFERENT,
    EXPERIMENT_VERDICT_IDENTICAL,
    EXPERIMENT_VERDICT_SAME_RESULT,
    BacktestExperimentMember,
    BacktestExperimentRequest,
)
from quant_platform.backtest.experiments import (
    build_experiment_result,
    hash_backtest_experiment,
)
from quant_platform.backtest.observations import contains_operative_language
from quant_platform.data import models as _models  # noqa: F401
from quant_platform.simulation.constructs import (
    FORBIDDEN_TABLE_NAMES,
    detect_trading_constructs,
)
from quant_platform.simulation.events import EVENT_PRIORITY
from quant_platform.storage.database import Base

_DIGEST_A = "sha256:" + ("a" * 64)
_DIGEST_B = "sha256:" + ("b" * 64)
_DIGEST_C = "sha256:" + ("c" * 64)
_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
_STAMP = datetime(2024, 1, 11, tzinfo=UTC)


def _load_script(filename: str):
    path = _SCRIPTS / filename
    spec = importlib.util.spec_from_file_location(filename.replace("-", "_"), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _request(**overrides: object) -> BacktestExperimentRequest:
    values: dict[str, object] = {
        "experiment_name": "noop-grid",
        "replay_ids": ("replay-a",),
        "policy_name": "noop",
        "deterministic_ids": True,
        "notes": "research dry-run grid",
    }
    values.update(overrides)
    return BacktestExperimentRequest(**values)  # type: ignore[arg-type]


def _member(**overrides: object) -> BacktestExperimentMember:
    values: dict[str, object] = {
        "replay_id": "replay-a",
        "backtest_id": "11111111-1111-4111-8111-111111111111",
        "stream_hash": _DIGEST_A,
        "backtest_hash": _DIGEST_B,
        "policy_name": "noop",
        "policy_config": {},
        "usable_result": True,
        "warning_count": 0,
        "error_count": 0,
        "relative_path": "runs/0001",
    }
    values.update(overrides)
    return BacktestExperimentMember(**values)  # type: ignore[arg-type]


def _write_member_stub(root: Path, member: BacktestExperimentMember) -> None:
    folder = root / member.relative_path
    folder.mkdir(parents=True, exist_ok=True)
    payload = {"backtest_id": member.backtest_id, "kind": "backtest_run"}
    (folder / "manifest.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )


def test_valid_request_normalizes_empty_configs() -> None:
    request = _request()
    assert request.policy_configs == ({},)
    assert request.replay_ids == ("replay-a",)


def test_request_without_replay_ids_fails() -> None:
    with pytest.raises(BacktestError) as exc:
        _request(replay_ids=())
    assert exc.value.code == BacktestErrorCode.CATALOG_INVALID


def test_unknown_policy_fails() -> None:
    with pytest.raises(BacktestError) as exc:
        _request(policy_name="momentum")
    assert exc.value.code == BacktestErrorCode.INVALID_POLICY


def test_non_json_safe_policy_config_fails() -> None:
    with pytest.raises(BacktestError) as exc:
        _request(policy_configs=({"window": {1, 2}},))
    assert exc.value.code == BacktestErrorCode.INVALID_POLICY


def test_experiment_hash_is_stable() -> None:
    request = _request()
    member = _member()
    first = build_experiment_result(request, (member,))
    second = build_experiment_result(request, (member,))
    assert hash_backtest_experiment(first) == hash_backtest_experiment(second)
    assert first.summary.experiment_hash.startswith("sha256:")
    assert len(first.summary.experiment_hash) == 71


def test_experiment_hash_changes_when_member_hash_changes() -> None:
    request = _request()
    left = build_experiment_result(request, (_member(),))
    right = build_experiment_result(request, (_member(backtest_hash=_DIGEST_C),))
    assert hash_backtest_experiment(left) != hash_backtest_experiment(right)


def test_experiment_hash_ignores_member_paths() -> None:
    request = _request()
    left = build_experiment_result(request, (_member(relative_path="runs/0001"),))
    right = build_experiment_result(request, (_member(relative_path="runs/0002"),))
    assert hash_backtest_experiment(left) == hash_backtest_experiment(right)


def test_manifest_has_relative_paths_and_no_secrets(tmp_path: Path) -> None:
    request = _request()
    member = _member()
    assembled = build_experiment_result(request, (member,))
    written = write_backtest_experiment_artifacts(
        assembled,
        tmp_path,
        created_at=_STAMP,
        git_commit="deadbeef",
        resolve_git=False,
    )
    assert written.manifest is not None
    _write_member_stub(tmp_path, member)
    manifest_text = (tmp_path / "experiment_manifest.json").read_text(encoding="utf-8")
    summary_text = (tmp_path / "experiment_summary.json").read_text(encoding="utf-8")
    assert "DATABASE_URL" not in manifest_text
    assert "postgresql://" not in manifest_text.lower()
    assert str(tmp_path) not in manifest_text
    payload = json.loads(manifest_text)
    for artifact in payload["artifacts"]:
        path = artifact["path"]
        assert not path.startswith("/")
        assert ".." not in path
    assert contains_operative_language(summary_text) is False
    report = verify_backtest_experiment_artifacts(tmp_path)
    assert report.ok is True
    assert report.recomputed_experiment_hash == written.summary.experiment_hash


def test_secret_like_notes_are_rejected(tmp_path: Path) -> None:
    request = _request(notes="see DATABASE_URL")
    assembled = build_experiment_result(request, (_member(),))
    with pytest.raises(BacktestError) as exc:
        write_backtest_experiment_artifacts(
            assembled,
            tmp_path,
            created_at=_STAMP,
            git_commit="deadbeef",
            resolve_git=False,
        )
    assert exc.value.code == BacktestErrorCode.CATALOG_INVALID


def test_compare_identical_same_result_and_different(tmp_path: Path) -> None:
    request = _request()
    member = _member()
    assembled = build_experiment_result(request, (member,))
    first = write_backtest_experiment_artifacts(
        assembled,
        tmp_path / "first",
        created_at=_STAMP,
        git_commit="deadbeef",
        resolve_git=False,
    )
    second = write_backtest_experiment_artifacts(
        assembled,
        tmp_path / "second",
        created_at=_STAMP + timedelta(seconds=1),
        git_commit="deadbeef",
        resolve_git=False,
    )
    other = write_backtest_experiment_artifacts(
        build_experiment_result(request, (_member(backtest_hash=_DIGEST_C),)),
        tmp_path / "other",
        created_at=_STAMP,
        git_commit="deadbeef",
        resolve_git=False,
    )
    assert first.manifest is not None
    assert second.manifest is not None
    assert other.manifest is not None
    identical = compare_backtest_experiments(first.manifest, first.manifest)
    assert identical.verdict == EXPERIMENT_VERDICT_IDENTICAL
    assert identical.identical is True
    same = compare_backtest_experiments(first.manifest, second.manifest)
    assert same.verdict == EXPERIMENT_VERDICT_SAME_RESULT
    assert same.same_experiment_hash is True
    assert same.same_manifest_hash is False
    different = compare_backtest_experiments(first.manifest, other.manifest)
    assert different.verdict == EXPERIMENT_VERDICT_DIFFERENT
    assert different.same_experiment_hash is False


def test_summary_has_no_forbidden_terms() -> None:
    result = build_experiment_result(_request(), (_member(),))
    blob = json.dumps(result.summary.as_mapping())
    assert contains_operative_language(blob) is False
    for token in ("pnl", "portfolio", "order", "trade", "signal"):
        assert token not in blob.lower()


def test_missing_member_manifest_fails_integrity(tmp_path: Path) -> None:
    assembled = build_experiment_result(_request(), (_member(),))
    write_backtest_experiment_artifacts(
        assembled,
        tmp_path,
        created_at=_STAMP,
        git_commit="deadbeef",
        resolve_git=False,
    )
    report = verify_backtest_experiment_artifacts(tmp_path)
    assert report.ok is False
    assert ExperimentIntegrityCode.MISSING_ARTIFACT.value in {
        item.code for item in report.issues
    }


def test_no_trading_constructs() -> None:
    findings = detect_trading_constructs(event_kinds=tuple(EVENT_PRIORITY))
    assert findings == ()
    names = set(Base.metadata.tables)
    assert "backtest_experiments" in names
    assert "backtest_runs" in names
    assert names.isdisjoint(FORBIDDEN_TABLE_NAMES)
    assert names.isdisjoint({"portfolio", "positions", "orders", "fills"})


def test_experiment_scripts_parse_args() -> None:
    for name in (
        "run-backtest-experiment.py",
        "list-backtest-experiments.py",
        "compare-backtest-experiments.py",
        "verify-backtest-experiment.py",
    ):
        script = _load_script(name)
        with pytest.raises(SystemExit) as help_exc:
            script.main(["--help"])
        assert help_exc.value.code == 0
