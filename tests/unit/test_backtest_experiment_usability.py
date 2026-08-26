"""Experiment usability gate and research reports without Docker."""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from quant_platform.backtest.errors import BacktestError, BacktestErrorCode
from quant_platform.backtest.experiment_artifacts import (
    write_backtest_experiment_artifacts,
)
from quant_platform.backtest.experiment_integrity import (
    ExperimentArtifactVerificationReport,
    verify_backtest_experiment_artifacts,
)
from quant_platform.backtest.experiment_readiness import (
    build_backtest_experiment_usability_report,
)
from quant_platform.backtest.experiment_readiness_types import (
    ExperimentUsabilityCode,
)
from quant_platform.backtest.experiment_report_artifacts import (
    write_backtest_experiment_report_artifacts,
)
from quant_platform.backtest.experiment_reports import (
    aggregate_experiment_observations,
    build_backtest_experiment_research_report,
    hash_backtest_experiment_report,
)
from quant_platform.backtest.experiment_types import (
    BacktestExperimentCatalogEntry,
    BacktestExperimentMember,
    BacktestExperimentRequest,
)
from quant_platform.backtest.experiments import build_experiment_result
from quant_platform.backtest.integrity_types import BacktestArtifactVerificationIssue
from quant_platform.backtest.observation_reports import (
    ObservationKindSummary,
    ObservationReport,
    ObservationSeveritySummary,
)
from quant_platform.backtest.observations import contains_operative_language
from quant_platform.backtest.readiness import (
    BacktestUsabilityGate,
    BacktestUsabilityReport,
)
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


def _entry(
    member: BacktestExperimentMember, **overrides: object
) -> BacktestExperimentCatalogEntry:
    values: dict[str, object] = {
        "experiment_id": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
        "experiment_name": "noop-grid",
        "experiment_hash": _DIGEST_A,
        "manifest_hash": _DIGEST_B,
        "policy_name": "noop",
        "package_version": "0.1.0",
        "git_commit": "deadbeef",
        "created_at": _STAMP,
        "member_count": 1,
        "usable_count": 1,
        "error_count": 0,
        "warning_count": 0,
        "request": {"experiment_name": "noop-grid", "policy_name": "noop"},
        "summary": {
            "members": [member.as_mapping()],
            "member_count": 1,
            "replay_ids": [member.replay_id],
            "policy_configs": [{}],
        },
        "artifacts": (),
        "notes": None,
        "registered_at": _STAMP,
    }
    values.update(overrides)
    return BacktestExperimentCatalogEntry(**values)  # type: ignore[arg-type]


def _integrity(**overrides: object) -> ExperimentArtifactVerificationReport:
    values: dict[str, object] = {
        "experiment_root": "exp",
        "experiment_id": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
        "ok": True,
        "error_count": 0,
        "warning_count": 0,
        "info_count": 0,
        "issues": (),
        "artifacts": (),
        "experiment_hash": _DIGEST_A,
        "recomputed_experiment_hash": _DIGEST_A,
        "manifest_hash": _DIGEST_B,
        "recomputed_manifest_hash": _DIGEST_B,
        "policy_name": "noop",
        "member_count": 1,
    }
    values.update(overrides)
    return ExperimentArtifactVerificationReport(**values)  # type: ignore[arg-type]


def _member_run(**overrides: object) -> BacktestUsabilityReport:
    usable = bool(overrides.pop("usable_result", True))
    artifacts_ok = bool(overrides.pop("artifacts_ok", True))
    policy_output_ok = bool(overrides.pop("policy_output_ok", True))
    values: dict[str, object] = {
        "backtest_id": "11111111-1111-4111-8111-111111111111",
        "usable_result": usable,
        "gate": BacktestUsabilityGate(
            usable_result=usable,
            research_mode=True,
            is_reproducible=True,
            is_usable=usable,
            artifacts_ok=artifacts_ok,
            policy_ok=True,
            backtest_hash_valid=True,
            manifest_hash_valid=True,
            replay_registered=True,
            policy_output_ok=policy_output_ok,
            error_count=0 if usable else 1,
            warning_count=0,
        ),
        "replay_id": "replay-a",
        "stream_hash": _DIGEST_A,
        "backtest_hash": _DIGEST_B,
        "manifest_hash": _DIGEST_B,
        "policy_name": "noop",
        "error_count": 0 if usable else 1,
        "warning_count": 0,
        "info_count": 0,
        "issues": (),
        "artifacts": (),
        "run_root": "runs/0001",
    }
    values.update(overrides)
    return BacktestUsabilityReport(**values)  # type: ignore[arg-type]


def _obs(*, kind: str, count: int, severity: str = "info") -> ObservationReport:
    return ObservationReport(
        policy_name="event_counting",
        policy_output_hash=_DIGEST_A,
        observation_count=count,
        warning_count=count if severity == "warning" else 0,
        error_count=count if severity == "error" else 0,
        unknown_event_count=count if kind == "unknown_event" else 0,
        correction_count=count if kind == "correction_seen" else 0,
        corporate_action_count=count if kind == "corporate_action_seen" else 0,
        session_count=count if kind == "session_seen" else 0,
        kinds=(ObservationKindSummary(kind=kind, count=count),),
        severities=(ObservationSeveritySummary(severity=severity, count=count),),
        instruments=(),
        first_observation=None,
        last_observation=None,
        issues=(),
    )


def test_empty_research_report_fails() -> None:
    with pytest.raises(BacktestError) as exc:
        build_backtest_experiment_research_report(
            experiment_id="exp",
            experiment_name="noop-grid",
            policy_name="noop",
            experiment_hash=_DIGEST_A,
            members=(),
        )
    assert exc.value.code == BacktestErrorCode.CATALOG_INVALID


def test_research_report_with_valid_members() -> None:
    report = build_backtest_experiment_research_report(
        experiment_id="exp",
        experiment_name="noop-grid",
        policy_name="noop",
        experiment_hash=_DIGEST_A,
        members=(_member(), _member(replay_id="replay-b", backtest_hash=_DIGEST_C)),
    )
    assert report.member_count == 2
    assert report.usable_count == 2
    assert report.report_hash.startswith("sha256:")
    assert len(report.report_hash) == 71
    assert report.comparison.distinct_stream_hash_count == 1
    assert report.comparison.distinct_backtest_hash_count == 2


def test_report_hash_is_stable_and_changes_with_member_hash() -> None:
    left = build_backtest_experiment_research_report(
        experiment_id="exp",
        experiment_name="noop-grid",
        policy_name="noop",
        experiment_hash=_DIGEST_A,
        members=(_member(),),
    )
    again = build_backtest_experiment_research_report(
        experiment_id="exp",
        experiment_name="noop-grid",
        policy_name="noop",
        experiment_hash=_DIGEST_A,
        members=(_member(),),
    )
    right = build_backtest_experiment_research_report(
        experiment_id="exp",
        experiment_name="noop-grid",
        policy_name="noop",
        experiment_hash=_DIGEST_A,
        members=(_member(backtest_hash=_DIGEST_C),),
    )
    assert hash_backtest_experiment_report(left) == left.report_hash
    assert left.report_hash == again.report_hash
    assert left.report_hash != right.report_hash


def test_observation_aggregation_by_kind_and_severity() -> None:
    aggregate = aggregate_experiment_observations(
        (
            _obs(kind="event_seen", count=3),
            _obs(kind="session_seen", count=2),
            _obs(kind="unknown_event", count=1, severity="warning"),
        )
    )
    kinds = {item.kind: item.count for item in aggregate.kinds}
    assert kinds["event_seen"] == 3
    assert kinds["session_seen"] == 2
    assert kinds["unknown_event"] == 1
    assert aggregate.observation_count == 6
    assert aggregate.unknown_event_count == 1
    assert aggregate.session_count == 2
    assert aggregate.warning_count == 1
    severities = {item.severity: item.count for item in aggregate.severities}
    assert severities["info"] == 5
    assert severities["warning"] == 1


def test_forbidden_language_blocks_usability() -> None:
    member = _member()
    integrity = _integrity(
        ok=False,
        error_count=1,
        issues=(
            BacktestArtifactVerificationIssue(
                severity="error",
                code="forbidden_operational_language",
                message="experiment metadata contains investment-decision wording",
                path="experiment_summary.json",
            ),
        ),
    )
    report = build_backtest_experiment_usability_report(
        experiment_id="exp",
        entry=_entry(member),
        integrity=integrity,
        member_reports=((member, _member_run()),),
        research_mode=True,
    )
    assert report.experiment_usable is False
    assert ExperimentUsabilityCode.FORBIDDEN_OPERATIONAL_LANGUAGE.value in {
        item.code for item in report.issues
    }


def test_member_not_usable_blocks_experiment() -> None:
    member = _member()
    report = build_backtest_experiment_usability_report(
        experiment_id="exp",
        entry=_entry(member),
        integrity=_integrity(),
        member_reports=((member, _member_run(usable_result=False)),),
        research_mode=True,
    )
    assert report.experiment_usable is False
    assert ExperimentUsabilityCode.MEMBER_NOT_USABLE.value in {
        item.code for item in report.issues
    }


def test_missing_artifact_blocks_experiment() -> None:
    member = _member()
    integrity = _integrity(
        ok=False,
        error_count=1,
        issues=(
            BacktestArtifactVerificationIssue(
                severity="error",
                code="missing_artifact",
                message="listed experiment artifact is missing",
                path="experiment_summary.json",
            ),
        ),
    )
    report = build_backtest_experiment_usability_report(
        experiment_id="exp",
        entry=_entry(member),
        integrity=integrity,
        member_reports=((member, _member_run()),),
        research_mode=True,
    )
    assert report.experiment_usable is False
    assert ExperimentUsabilityCode.EXPERIMENT_ARTIFACT_MISSING.value in {
        item.code for item in report.issues
    }


def test_research_report_has_no_forbidden_metrics() -> None:
    report = build_backtest_experiment_research_report(
        experiment_id="exp",
        experiment_name="noop-grid",
        policy_name="noop",
        experiment_hash=_DIGEST_A,
        members=(_member(),),
        observation_reports=(_obs(kind="event_seen", count=1),),
    )
    blob = json.dumps(report.as_mapping())
    assert contains_operative_language(blob) is False
    for token in ("pnl", "returns", "portfolio", "orders", "trades", "sharpe"):
        assert token not in blob.lower()
    assert "drawdown" not in blob.lower()
    assert "hit_ratio" not in blob.lower()


def test_listed_research_report_missing_fails_integrity(tmp_path: Path) -> None:
    member = _member()
    assembled = build_experiment_result(
        BacktestExperimentRequest(
            experiment_name="noop-grid",
            replay_ids=("replay-a",),
            policy_name="noop",
            deterministic_ids=True,
            notes="research dry-run grid",
        ),
        (member,),
    )
    write_backtest_experiment_artifacts(
        assembled,
        tmp_path,
        created_at=_STAMP,
        git_commit="deadbeef",
        resolve_git=False,
    )
    folder = tmp_path / member.relative_path
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "manifest.json").write_text(
        json.dumps({"backtest_id": member.backtest_id}) + "\n", encoding="utf-8"
    )
    manifest_path = tmp_path / "experiment_manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifacts = payload.get("artifacts")
    assert isinstance(artifacts, list)
    artifacts.append(
        {
            "name": "research_report",
            "path": "experiment_research_report.json",
            "kind": "json",
        }
    )
    manifest_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    report = verify_backtest_experiment_artifacts(tmp_path)
    assert report.ok is False
    assert any(item.code == "missing_artifact" for item in report.issues)


def test_unlisted_research_report_does_not_break_old_experiments(
    tmp_path: Path,
) -> None:
    member = _member()
    assembled = build_experiment_result(
        BacktestExperimentRequest(
            experiment_name="noop-grid",
            replay_ids=("replay-a",),
            policy_name="noop",
            deterministic_ids=True,
            notes="research dry-run grid",
        ),
        (member,),
    )
    write_backtest_experiment_artifacts(
        assembled,
        tmp_path,
        created_at=_STAMP,
        git_commit="deadbeef",
        resolve_git=False,
    )
    folder = tmp_path / member.relative_path
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "manifest.json").write_text(
        json.dumps({"backtest_id": member.backtest_id}) + "\n", encoding="utf-8"
    )
    (tmp_path / "experiment_research_report.json").write_text("{}\n", encoding="utf-8")
    report = verify_backtest_experiment_artifacts(tmp_path)
    assert report.ok is True


def test_write_report_artifacts_uses_relative_paths(tmp_path: Path) -> None:
    report = build_backtest_experiment_research_report(
        experiment_id="exp",
        experiment_name="noop-grid",
        policy_name="noop",
        experiment_hash=_DIGEST_A,
        members=(_member(),),
    )
    write_backtest_experiment_report_artifacts(report, tmp_path)
    text = (tmp_path / "experiment_research_report.json").read_text(encoding="utf-8")
    assert "DATABASE_URL" not in text
    assert str(tmp_path) not in text
    payload = json.loads(text)
    assert payload["report_hash"] == report.report_hash


def test_no_trading_constructs() -> None:
    findings = detect_trading_constructs(event_kinds=tuple(EVENT_PRIORITY))
    assert findings == ()
    names = set(Base.metadata.tables)
    assert names.isdisjoint(FORBIDDEN_TABLE_NAMES)
    assert names.isdisjoint({"portfolio", "orders", "fills"})


def test_usability_scripts_parse_args() -> None:
    for name in (
        "check-backtest-experiment-usability.py",
        "report-backtest-experiment.py",
        "list-backtest-experiments.py",
    ):
        script = _load_script(name)
        with pytest.raises(SystemExit) as help_exc:
            script.main(["--help"])
        assert help_exc.value.code == 0
