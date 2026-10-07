"""Research evidence-bundle checks without Docker. No trading."""

from __future__ import annotations

import importlib.util
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from quant_platform.release.evidence_bundle import hash_research_evidence_bundle
from quant_platform.release.evidence_contract_intake import (
    run_evidence_contract_payload_intake,
)
from quant_platform.release.evidence_integrity import (
    EvidenceIntegrityCode,
    verify_research_evidence_bundle,
)
from quant_platform.release.evidence_types import (
    EVIDENCE_MANIFEST_NAME,
    EVIDENCE_SUMMARY_NAME,
    RELEASE_STATUS_NAME,
    EvidenceBundleError,
    EvidenceFixtureDataMode,
    ResearchEvidenceBundleArtifact,
    ResearchEvidenceBundleIssue,
    ResearchEvidenceBundleManifest,
    ResearchEvidenceBundleRequest,
    ResearchEvidenceBundleStep,
    empty_fixture_reuse_report,
)
from quant_platform.simulation.constructs import detect_trading_constructs

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _ROOT / "scripts"
_FAKE_HASH = "sha256:" + ("a" * 64)
_OTHER_HASH = "sha256:" + ("b" * 64)
_STAMP = datetime(2024, 1, 2, tzinfo=UTC)


def _load_script(filename: str):
    path = _SCRIPTS / filename
    spec = importlib.util.spec_from_file_location(filename.replace("-", "_"), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _assert_no_secrets(blob: str) -> None:
    lowered = blob.lower()
    assert "postgresql+psycopg://" not in lowered
    assert "quant_dev_only_not_for_production" not in lowered
    assert "://quant:" not in lowered
    assert "DATABASE_URL" not in blob


def _manifest(
    **overrides: object,
) -> ResearchEvidenceBundleManifest:
    payload: dict[str, object] = {
        "bundle_id": "11111111-1111-1111-1111-111111111111",
        "created_at": _STAMP,
        "package_version": "0.1.0",
        "git_commit": "deadbeef",
        "app_mode": "research",
        "alembic_head": "0009_backtest_experiments",
        "dataset_snapshot_id": "snap-1",
        "replay_id": "replay-1",
        "backtest_id": "backtest-1",
        "experiment_id": "experiment-1",
        "snapshot_hash": _FAKE_HASH,
        "stream_hash": _FAKE_HASH,
        "backtest_hash": _FAKE_HASH,
        "experiment_hash": _FAKE_HASH,
        "report_hash": _FAKE_HASH,
        "release_report_hash": _FAKE_HASH,
        "steps": (
            ResearchEvidenceBundleStep(name="validate_research_mode", status="ok"),
            ResearchEvidenceBundleStep(name="replay_run", status="ok"),
        ),
        "artifacts": (
            ResearchEvidenceBundleArtifact(
                name="manifest", path=EVIDENCE_MANIFEST_NAME, kind="json"
            ),
        ),
        "warnings": (),
        "errors": (),
        "ok": True,
        "bundle_hash": "",
        "replay_ready": True,
        "backtest_usable": True,
        "experiment_usable": True,
        "release_ok": True,
        "policy_name": "data_quality",
    }
    payload.update(overrides)
    return ResearchEvidenceBundleManifest(**payload)  # type: ignore[arg-type]


def _write_valid_bundle(root: Path) -> ResearchEvidenceBundleManifest:
    draft = _manifest()
    digest = hash_research_evidence_bundle(draft)
    manifest = replace(draft, bundle_hash=digest)
    payload = manifest.as_mapping()
    summary = {
        "kind": payload["kind"],
        "format_version": payload["format_version"],
        "bundle_id": payload["bundle_id"],
        "created_at": payload["created_at"],
        "package_version": payload["package_version"],
        "git_commit": payload["git_commit"],
        "app_mode": payload["app_mode"],
        "alembic_head": payload["alembic_head"],
        "policy_name": payload["policy_name"],
        "snapshot_hash": payload["snapshot_hash"],
        "stream_hash": payload["stream_hash"],
        "backtest_hash": payload["backtest_hash"],
        "experiment_hash": payload["experiment_hash"],
        "report_hash": payload["report_hash"],
        "release_report_hash": payload["release_report_hash"],
        "ok": payload["ok"],
        "bundle_hash": payload["bundle_hash"],
        "step_count": payload["step_count"],
        "error_count": payload["error_count"],
        "steps": payload["steps"],
        "artifacts": payload["artifacts"],
        "errors": payload["errors"],
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / EVIDENCE_MANIFEST_NAME).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (root / EVIDENCE_SUMMARY_NAME).write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (root / RELEASE_STATUS_NAME).write_text("{}\n", encoding="utf-8")
    return manifest


def test_manifest_serializes_without_secrets() -> None:
    blob = json.dumps(_manifest().as_mapping(), sort_keys=True)
    _assert_no_secrets(blob)
    assert "buy" not in blob.lower()
    assert "portfolio" not in blob.lower()


def test_artifact_paths_must_be_relative() -> None:
    artifact = ResearchEvidenceBundleArtifact(
        name="escaped", path="/var/absolute/secret.json", kind="json"
    )
    with pytest.raises(EvidenceBundleError, match="relative"):
        artifact.as_mapping()


def test_path_traversal_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    manifest = _write_valid_bundle(root)
    payload = manifest.as_mapping()
    payload["artifacts"] = [
        {"name": "escaped", "path": "../secret.json", "kind": "json"}
    ]
    (root / EVIDENCE_MANIFEST_NAME).write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    report = verify_research_evidence_bundle(root)
    assert report.ok is False
    codes = {item.code for item in report.issues}
    assert EvidenceIntegrityCode.PATH_ESCAPE.value in codes


def test_bundle_hash_is_stable_across_ids_and_clock() -> None:
    left = _manifest(
        bundle_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
        git_commit="one",
    )
    right = _manifest(
        bundle_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        created_at=datetime(2025, 12, 31, tzinfo=UTC),
        git_commit="two",
    )
    assert hash_research_evidence_bundle(left) == hash_research_evidence_bundle(right)
    assert hash_research_evidence_bundle(left) == hash_research_evidence_bundle(
        left.as_mapping()
    )


def test_bundle_hash_changes_when_stream_hash_changes() -> None:
    left = hash_research_evidence_bundle(_manifest(stream_hash=_FAKE_HASH))
    right = hash_research_evidence_bundle(_manifest(stream_hash=_OTHER_HASH))
    assert left != right
    assert left.startswith("sha256:")
    assert len(left) == 71


def test_forbidden_terms_are_detected(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    manifest = _write_valid_bundle(root)
    payload = manifest.as_mapping()
    payload["errors"] = [
        {
            "severity": "error",
            "code": "demo",
            "message": "do not buy this research note",
            "step": None,
        }
    ]
    (root / EVIDENCE_MANIFEST_NAME).write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    report = verify_research_evidence_bundle(root)
    assert report.ok is False
    codes = {item.code for item in report.issues}
    assert EvidenceIntegrityCode.OPERATIVE_LANGUAGE.value in codes


def test_evidence_integrity_missing_manifest(tmp_path: Path) -> None:
    report = verify_research_evidence_bundle(tmp_path / "missing")
    assert report.ok is False
    codes = {item.code for item in report.issues}
    assert EvidenceIntegrityCode.MISSING_MANIFEST.value in codes
    assert EvidenceIntegrityCode.MISSING_SUMMARY.value in codes
    assert EvidenceIntegrityCode.MISSING_RELEASE_STATUS.value in codes


def test_evidence_integrity_valid_fixture(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    _write_valid_bundle(root)
    report = verify_research_evidence_bundle(root)
    assert report.ok is True
    assert report.bundle_hash == report.recomputed_bundle_hash
    assert report.error_count == 0


def test_verify_script_json_has_no_database_url(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "bundle"
    _write_valid_bundle(root)
    runner = _load_script("verify-research-evidence-bundle.py")
    code = runner.main(["--bundle-dir", str(root), "--json"])
    captured = capsys.readouterr()
    assert code == 0
    _assert_no_secrets(captured.out)
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert payload["kind"] == "research_evidence_bundle_integrity"


def test_build_script_rejects_invalid_policy_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    runner = _load_script("build-research-evidence-bundle.py")
    code = runner.main(
        [
            "--fixture-dir",
            "/var/unused",
            "--output-dir",
            "/var/unused-out",
            "--policy-config-json",
            "[1]",
        ]
    )
    captured = capsys.readouterr()
    assert code == 1
    _assert_no_secrets(captured.err + captured.out)
    assert "JSON object" in captured.err


def test_no_trading_constructs_in_research_package() -> None:
    findings = detect_trading_constructs()
    assert findings == ()
    issue = ResearchEvidenceBundleIssue(
        severity="error", code="demo", message="quality note only"
    )
    blob = json.dumps(issue.as_mapping())
    assert "strategy" not in blob
    assert "signal" not in blob
    assert "order" not in blob
    assert "fill" not in blob
    assert "portfolio" not in blob
    assert "pnl" not in blob


def test_request_default_disallows_fixture_reuse(tmp_path: Path) -> None:
    request = ResearchEvidenceBundleRequest(
        fixture_dir=tmp_path / "fixtures",
        output_dir=tmp_path / "bundle",
    )
    assert request.allow_existing_fixture_data is False


def test_manifest_serializes_fixture_data_mode() -> None:
    reuse = empty_fixture_reuse_report(
        mode=EvidenceFixtureDataMode.REUSED.value,
        reused_bar_count=2,
        reused_corporate_action_count=1,
        reused_session_count=4,
    )
    payload = _manifest(
        fixture_data_mode=EvidenceFixtureDataMode.REUSED.value,
        fixture_reuse=reuse,
    ).as_mapping()
    blob = json.dumps(payload, sort_keys=True)
    _assert_no_secrets(blob)
    assert payload["fixture_data_mode"] == "reused"
    assert payload["fixture_reuse"]["reused_bar_count"] == 2
    assert "/home/" not in blob
    assert "pnl" not in blob.lower()
    assert "returns" not in blob.lower()
    assert "strategy" not in blob.lower()


def test_bundle_hash_changes_when_fixture_data_mode_changes() -> None:
    inserted = empty_fixture_reuse_report(
        mode=EvidenceFixtureDataMode.INSERTED.value,
        inserted_bar_count=2,
    )
    reused = empty_fixture_reuse_report(
        mode=EvidenceFixtureDataMode.REUSED.value,
        reused_bar_count=2,
    )
    left = hash_research_evidence_bundle(
        _manifest(
            fixture_data_mode=EvidenceFixtureDataMode.INSERTED.value,
            fixture_reuse=inserted,
        )
    )
    right = hash_research_evidence_bundle(
        _manifest(
            fixture_data_mode=EvidenceFixtureDataMode.REUSED.value,
            fixture_reuse=reused,
        )
    )
    assert left != right
    assert left.startswith("sha256:")


def test_evidence_integrity_accepts_inserted_and_reused(tmp_path: Path) -> None:
    for mode in (
        EvidenceFixtureDataMode.INSERTED.value,
        EvidenceFixtureDataMode.REUSED.value,
    ):
        root = tmp_path / mode
        reuse = empty_fixture_reuse_report(mode=mode, inserted_bar_count=1)
        draft = _manifest(fixture_data_mode=mode, fixture_reuse=reuse)
        digest = hash_research_evidence_bundle(draft)
        manifest = replace(draft, bundle_hash=digest)
        _write_payload_bundle(root, manifest)
        report = verify_research_evidence_bundle(root)
        assert report.ok is True, report.issues


def test_evidence_integrity_rejects_invalid_fixture_data_mode(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    manifest = _write_valid_bundle(root)
    payload = manifest.as_mapping()
    payload["fixture_data_mode"] = "upsert"
    payload["bundle_hash"] = hash_research_evidence_bundle(payload)
    (root / EVIDENCE_MANIFEST_NAME).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    report = verify_research_evidence_bundle(root)
    assert report.ok is False
    codes = {item.code for item in report.issues}
    assert EvidenceIntegrityCode.INVALID_FIXTURE_DATA_MODE.value in codes


def test_evidence_integrity_rejects_failed_mode_when_ok(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    reuse = empty_fixture_reuse_report(mode=EvidenceFixtureDataMode.FAILED.value)
    draft = _manifest(
        ok=True,
        fixture_data_mode=EvidenceFixtureDataMode.FAILED.value,
        fixture_reuse=reuse,
    )
    digest = hash_research_evidence_bundle(draft)
    _write_payload_bundle(root, replace(draft, bundle_hash=digest))
    report = verify_research_evidence_bundle(root)
    assert report.ok is False
    codes = {item.code for item in report.issues}
    assert EvidenceIntegrityCode.FIXTURE_DATA_FAILED.value in codes


def test_evidence_integrity_rejects_negative_reuse_count(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    reuse = empty_fixture_reuse_report(
        mode=EvidenceFixtureDataMode.REUSED.value,
        reused_bar_count=-1,
    )
    draft = _manifest(
        fixture_data_mode=EvidenceFixtureDataMode.REUSED.value,
        fixture_reuse=reuse,
    )
    digest = hash_research_evidence_bundle(draft)
    _write_payload_bundle(root, replace(draft, bundle_hash=digest))
    report = verify_research_evidence_bundle(root)
    assert report.ok is False
    codes = {item.code for item in report.issues}
    assert EvidenceIntegrityCode.NEGATIVE_REUSE_COUNT.value in codes


def test_build_script_help_mentions_allow_existing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    runner = _load_script("build-research-evidence-bundle.py")
    with pytest.raises(SystemExit) as exc:
        runner.main(["--help"])
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "--allow-existing-fixture-data" in captured.out
    assert "--include-contract-payload-intake" in captured.out
    assert "--contract-intake-write-db" in captured.out
    _assert_no_secrets(captured.out)


def _intake_manifest_fields(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "contract_intake_included": True,
        "contract_intake_write_db": False,
        "contract_intake_hash": _FAKE_HASH,
        "contract_intake_batch_hash": _FAKE_HASH,
        "contract_intake_status": "dry_run",
        "contract_intake_artifact_status": "ok",
        "contract_intake_db_status": "not_executed",
        "contract_intake_inserted_counts": {
            "daily_bars": 0,
            "corporate_actions": 0,
            "market_sessions": 0,
            "total": 0,
        },
        "contract_intake_skipped_counts": {
            "daily_bars": 0,
            "corporate_actions": 0,
            "market_sessions": 0,
            "total": 0,
        },
    }
    payload.update(overrides)
    return payload


def test_request_default_omits_contract_intake(tmp_path: Path) -> None:
    request = ResearchEvidenceBundleRequest(
        fixture_dir=tmp_path / "fixtures",
        output_dir=tmp_path / "bundle",
    )
    assert request.include_contract_payload_intake is False
    assert request.contract_intake_write_db is False
    payload = _manifest().as_mapping()
    assert "contract_intake_included" not in payload
    assert "contract_intake_hash" not in payload
    blob = json.dumps(payload, sort_keys=True)
    assert "contract_payload_intake" not in blob
    _assert_no_secrets(blob)


def test_default_bundle_hash_unchanged_without_intake() -> None:
    left = hash_research_evidence_bundle(_manifest())
    right = hash_research_evidence_bundle(
        _manifest(
            contract_intake_included=None,
            contract_intake_hash=None,
            contract_intake_write_db=None,
        )
    )
    assert left == right


def test_bundle_hash_changes_when_intake_hash_changes() -> None:
    left = hash_research_evidence_bundle(_manifest(**_intake_manifest_fields()))
    right = hash_research_evidence_bundle(
        _manifest(**_intake_manifest_fields(contract_intake_hash=_OTHER_HASH))
    )
    assert left != right
    assert left.startswith("sha256:")


def test_intake_rejects_ambiguous_source(tmp_path: Path) -> None:
    request = ResearchEvidenceBundleRequest(
        fixture_dir=tmp_path / "fixtures",
        output_dir=tmp_path / "bundle",
        include_contract_payload_intake=True,
        contract_intake_batch_file=tmp_path / "batch.json",
        contract_intake_fixture_dir=tmp_path / "fixtures-intake",
    )
    with pytest.raises(EvidenceBundleError, match="only one"):
        run_evidence_contract_payload_intake(request, tmp_path / "bundle")
    root = tmp_path / "bundle"
    request = ResearchEvidenceBundleRequest(
        fixture_dir=tmp_path / "fixtures",
        output_dir=root,
        include_contract_payload_intake=True,
    )
    outcome = run_evidence_contract_payload_intake(request, root)
    assert outcome.included is True
    assert outcome.write_db is False
    assert outcome.inserted_counts["total"] == 0
    assert outcome.report.db_executed is False
    assert outcome.status == "dry_run"
    intake_dir = root / "contract_payload_intake"
    assert (intake_dir / "contract_payload_intake_plan.json").is_file()
    assert (intake_dir / "contract_payload_intake_report.json").is_file()
    assert (intake_dir / "contract_payload_intake_manifest.json").is_file()
    blob = json.dumps(outcome.report.as_mapping(), sort_keys=True)
    _assert_no_secrets(blob)
    assert "/home/" not in blob
    assert "pnl" not in blob.lower()
    assert "returns" not in blob.lower()


def test_integrity_accepts_intake_dry_run(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    request = ResearchEvidenceBundleRequest(
        fixture_dir=tmp_path / "fixtures",
        output_dir=root,
        include_contract_payload_intake=True,
    )
    outcome = run_evidence_contract_payload_intake(request, root)
    artifacts = _manifest().artifacts + outcome.artifacts
    draft = _manifest(
        artifacts=artifacts,
        contract_intake_artifacts=outcome.artifacts,
        **_intake_manifest_fields(
            contract_intake_hash=outcome.intake_hash,
            contract_intake_batch_hash=outcome.batch_hash,
        ),
    )
    digest = hash_research_evidence_bundle(draft)
    _write_payload_bundle(root, replace(draft, bundle_hash=digest))
    report = verify_research_evidence_bundle(root)
    assert report.ok is True, report.issues


def test_integrity_rejects_intake_without_artifacts(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    draft = _manifest(**_intake_manifest_fields())
    digest = hash_research_evidence_bundle(draft)
    _write_payload_bundle(root, replace(draft, bundle_hash=digest))
    report = verify_research_evidence_bundle(root)
    assert report.ok is False
    codes = {item.code for item in report.issues}
    assert EvidenceIntegrityCode.CONTRACT_INTAKE_MISSING.value in codes


def test_integrity_rejects_write_db_false_with_inserts(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    request = ResearchEvidenceBundleRequest(
        fixture_dir=tmp_path / "fixtures",
        output_dir=root,
        include_contract_payload_intake=True,
    )
    outcome = run_evidence_contract_payload_intake(request, root)
    artifacts = _manifest().artifacts + outcome.artifacts
    draft = _manifest(
        artifacts=artifacts,
        contract_intake_artifacts=outcome.artifacts,
        **_intake_manifest_fields(
            contract_intake_hash=outcome.intake_hash,
            contract_intake_batch_hash=outcome.batch_hash,
            contract_intake_inserted_counts={
                "daily_bars": 1,
                "corporate_actions": 0,
                "market_sessions": 0,
                "total": 1,
            },
        ),
    )
    digest = hash_research_evidence_bundle(draft)
    _write_payload_bundle(root, replace(draft, bundle_hash=digest))
    report = verify_research_evidence_bundle(root)
    assert report.ok is False
    codes = {item.code for item in report.issues}
    assert EvidenceIntegrityCode.CONTRACT_INTAKE_WRITE_MISMATCH.value in codes


def test_evidence_intake_module_has_no_network_or_vendors() -> None:
    root = Path(__file__).resolve().parents[2]
    path = root / "src" / "quant_platform" / "release" / "evidence_contract_intake.py"
    blob = path.read_text(encoding="utf-8").lower()
    assert "import requests" not in blob
    assert "import httpx" not in blob
    assert "import aiohttp" not in blob
    assert "urllib.request" not in blob
    assert "polygon" not in blob
    assert "yfinance" not in blob
    assert "alpaca" not in blob


def test_build_script_rejects_write_db_without_include(
    capsys: pytest.CaptureFixture[str],
) -> None:
    runner = _load_script("build-research-evidence-bundle.py")
    code = runner.main(
        [
            "--fixture-dir",
            "/var/unused",
            "--output-dir",
            "/var/unused-out",
            "--contract-intake-write-db",
        ]
    )
    captured = capsys.readouterr()
    assert code == 1
    assert "include-contract-payload-intake" in captured.err
    _assert_no_secrets(captured.err + captured.out)


def test_evidence_intake_remote_verification_doc() -> None:
    spec = _ROOT / "docs" / "release" / "EVIDENCE_INTAKE_REMOTE_RELEASE_VERIFICATION.md"
    assert spec.is_file()
    raw = spec.read_text(encoding="utf-8")
    text = " ".join(raw.replace("*", " ").lower().split())
    assert "v0.6.0-research-evidence-intake" in raw
    assert "0010_normalized_dataset_catalog" in raw
    assert "evidence bundle" in text
    assert "contract payload intake" in text
    assert "opt-in" in text
    assert "dry-run" in text
    assert "--contract-intake-write-db" in raw
    assert "no vendors reales" in text
    assert "no internet" in text
    assert "no trading" in text
    assert "no pnl/returns" in text
    assert "DATABASE_URL=" not in raw
    assert "postgresql+psycopg://quant:" not in text
    assert "quant_dev_only_not_for_production" not in text


def _write_payload_bundle(root: Path, manifest: ResearchEvidenceBundleManifest) -> None:
    payload = manifest.as_mapping()
    summary = {
        "kind": payload["kind"],
        "format_version": payload["format_version"],
        "bundle_id": payload["bundle_id"],
        "created_at": payload["created_at"],
        "package_version": payload["package_version"],
        "git_commit": payload["git_commit"],
        "app_mode": payload["app_mode"],
        "alembic_head": payload["alembic_head"],
        "policy_name": payload["policy_name"],
        "snapshot_hash": payload["snapshot_hash"],
        "stream_hash": payload["stream_hash"],
        "backtest_hash": payload["backtest_hash"],
        "experiment_hash": payload["experiment_hash"],
        "report_hash": payload["report_hash"],
        "release_report_hash": payload["release_report_hash"],
        "ok": payload["ok"],
        "bundle_hash": payload["bundle_hash"],
        "step_count": payload["step_count"],
        "error_count": payload["error_count"],
        "steps": payload["steps"],
        "artifacts": payload["artifacts"],
        "errors": payload["errors"],
        "fixture_data_mode": payload.get("fixture_data_mode"),
        "fixture_reuse": payload.get("fixture_reuse"),
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / EVIDENCE_MANIFEST_NAME).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (root / EVIDENCE_SUMMARY_NAME).write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (root / RELEASE_STATUS_NAME).write_text("{}\n", encoding="utf-8")
