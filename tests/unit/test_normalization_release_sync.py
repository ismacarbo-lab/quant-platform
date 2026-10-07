"""Operational docs and status keep the 0010 normalization catalog context."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from quant_platform.core.config import Settings
from quant_platform.release.constants import EXPECTED_ALEMBIC_HEAD
from quant_platform.release.status import build_release_status
from quant_platform.research.normalization.status import (
    DIVIDEND_POLICY,
    EXPECTED_CATALOG_TABLE,
    build_normalization_status,
)

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _ROOT / "scripts"
_CATALOG_REVISION = "0010_normalized_dataset_catalog"
_FREEZE_HEAD = "0009_backtest_experiments"
_FREEZE_TAG = "v0.1.0-research"

_OPERATIONAL_DOCS = (
    "README.md",
    "docs/architecture/ARCHITECTURE.md",
    "docs/development/DEVELOPER_WORKFLOW.md",
    "docs/release/COMMANDS.md",
    "docs/release/RISK_REGISTER.md",
    "docs/release/RESEARCH_RELEASE_CANDIDATE.md",
    "docs/release/RESEARCH_EVIDENCE_BUNDLE.md",
    "docs/release/MINIMAL_REPRODUCIBLE_EXAMPLE.md",
    "docs/release/NORMALIZATION_ADDON_VERIFICATION.md",
    "docs/research/CORPORATE_ACTION_NORMALIZATION.md",
    "docs/research/NORMALIZED_DATASET_CATALOG.md",
    "docs/research/NORMALIZATION_REGRESSION_MATRIX.md",
    "alembic/README.md",
)

_HISTORICAL_DOCS = (
    "docs/release/RESEARCH_HANDOFF.md",
    "docs/release/REMOTE_RELEASE_VERIFICATION.md",
    "docs/release/POST_TAG_RELEASE_NOTES.md",
    "docs/release/FINAL_RESEARCH_CHECKLIST.md",
    "docs/adr/0003-research-mode-freeze.md",
)


def _read(relative: str) -> str:
    return (_ROOT / relative).read_text(encoding="utf-8")


def _load_script(filename: str):
    path = _SCRIPTS / filename
    spec = importlib.util.spec_from_file_location(filename.replace("-", "_"), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_expected_alembic_head_is_at_or_after_0010() -> None:
    assert EXPECTED_ALEMBIC_HEAD >= _CATALOG_REVISION


def test_operational_docs_mention_0010() -> None:
    for relative in _OPERATIONAL_DOCS:
        text = _read(relative)
        assert _CATALOG_REVISION in text, relative


def test_historical_docs_that_mention_0009_keep_freeze_context() -> None:
    for relative in _HISTORICAL_DOCS:
        text = _read(relative)
        if _FREEZE_HEAD not in text:
            continue
        assert _FREEZE_TAG in text, relative


def test_capability_matrix_mentions_metadata_only_catalog() -> None:
    text = _read("docs/release/CAPABILITY_MATRIX.md")
    lowered = text.lower()
    assert "normalized_datasets" in text
    assert "metadata" in lowered
    assert "not normalized bars" in lowered


def test_commands_document_normalization_regression() -> None:
    text = _read("docs/release/COMMANDS.md")
    assert "make normalization-regression" in text
    assert "normalization-status.py" in text


def test_risk_register_dividend_informational_only() -> None:
    text = _read("docs/release/RISK_REGISTER.md").lower()
    assert "dividend" in text
    assert "informational only" in text


def test_readme_says_paper_only_no_live_trading() -> None:
    raw = _read("README.md").lower().replace("*", " ")
    text = " ".join(raw.split())
    assert "no live trading" in text
    assert "no real money" in text
    assert "paper trading" in text


def test_release_docs_have_no_live_database_url() -> None:
    release_dir = _ROOT / "docs" / "release"
    for path in sorted(release_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        assert "postgresql+psycopg://quant:" not in lowered, path.name
        assert "quant_dev_only_not_for_production" not in lowered, path.name
        assert "DATABASE_URL=" not in text, path.name


def test_normalization_remote_verification_doc() -> None:
    relative = "docs/release/NORMALIZATION_REMOTE_RELEASE_VERIFICATION.md"
    raw = _read(relative)
    text = " ".join(raw.replace("*", " ").lower().split())
    assert _CATALOG_REVISION in raw
    assert "v0.2.0-research-normalization" in raw
    assert "normalized_datasets" in raw
    assert "metadata-only" in text
    assert "no trading" in text
    assert "pnl" in text
    assert "returns" in text
    assert "postgresql+psycopg://quant:" not in text
    assert "DATABASE_URL=" not in raw


def test_normalization_post_tag_release_notes() -> None:
    relative = "docs/release/NORMALIZATION_POST_TAG_RELEASE_NOTES.md"
    raw = _read(relative)
    text = " ".join(raw.replace("*", " ").lower().split())
    assert "v0.2.0-research-normalization" in raw
    assert "83610f2131b7bd69ce5a15e455f7b92ab21144f4" in raw
    assert _CATALOG_REVISION in raw
    assert "no trading" in text
    assert "pnl" in text
    assert "returns" in text
    assert "postgresql+psycopg://quant:" not in text
    assert "DATABASE_URL=" not in raw


def test_normalization_status_script_help_and_json(
    monkeypatch: pytest.MonkeyPatch,
    research_settings: Settings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_script("normalization-status.py")
    with pytest.raises(SystemExit) as help_exc:
        module.main(["--help"])
    assert help_exc.value.code == 0
    capsys.readouterr()
    monkeypatch.setattr(module, "get_settings", lambda: research_settings)
    code = module.main(["--json"])
    captured = capsys.readouterr()
    assert code == 0
    payload = json.loads(captured.out)
    assert payload["expected_alembic_head"] == EXPECTED_ALEMBIC_HEAD
    assert payload["dividend_policy"] == DIVIDEND_POLICY
    assert "DATABASE_URL" not in captured.out
    assert "postgresql+psycopg://" not in captured.out


def test_status_json_has_expected_alembic_head(research_settings: Settings) -> None:
    report = build_release_status(settings=research_settings)
    payload = report.as_mapping()
    assert payload["alembic_head_expected"] == EXPECTED_ALEMBIC_HEAD
    blob = json.dumps(payload, sort_keys=True)
    assert "DATABASE_URL" not in blob
    assert "postgresql+psycopg://" not in blob


def test_normalization_status_without_database(research_settings: Settings) -> None:
    del research_settings
    report = build_normalization_status(check_db=False)
    assert report.ok is True
    assert report.capability_enabled is True
    assert report.expected_alembic_head == EXPECTED_ALEMBIC_HEAD
    assert report.expected_table == EXPECTED_CATALOG_TABLE
    assert report.regression_case_count >= 6
    assert "split_only" in report.adjustment_modes
    assert report.dividend_policy == DIVIDEND_POLICY
    assert report.database_checked is False
    blob = json.dumps(report.as_mapping(), sort_keys=True)
    assert "DATABASE_URL" not in blob
    assert "postgresql+psycopg://" not in blob
