"""Research-mode freeze docs and status. No trading."""

from __future__ import annotations

import json
from pathlib import Path

from quant_platform.core.config import Settings
from quant_platform.release.constants import (
    EXPECTED_ALEMBIC_HEAD,
    FREEZE_DOC_PATHS,
)
from quant_platform.release.status import (
    alembic_script_heads,
    build_release_status,
    evidence_bundle_available,
    final_freeze_ready,
    freeze_docs_available,
    repository_root,
)

_ROOT = Path(__file__).resolve().parents[2]
_README = _ROOT / "README.md"
_CAPABILITY = _ROOT / "docs" / "release" / "CAPABILITY_MATRIX.md"
_CHECKLIST = _ROOT / "docs" / "release" / "FINAL_RESEARCH_CHECKLIST.md"
_COMMANDS = _ROOT / "docs" / "release" / "COMMANDS.md"
_RISKS = _ROOT / "docs" / "release" / "RISK_REGISTER.md"
_ADR = _ROOT / "docs" / "adr" / "0003-research-mode-freeze.md"


def test_freeze_and_handoff_docs_exist() -> None:
    root = repository_root()
    assert freeze_docs_available(root) is True
    for relative in FREEZE_DOC_PATHS:
        assert (root / relative).is_file()
    assert _ADR.is_file()
    assert "research-mode freeze" in _ADR.read_text(encoding="utf-8").lower()


def test_readme_is_research_only_and_not_trading() -> None:
    raw = _README.read_text(encoding="utf-8").lower().replace("*", " ")
    text = " ".join(raw.split())
    assert "research-only" in text
    assert "not a trading system" in text
    assert "docs/release/research_handoff.md" in text
    assert "docs/release/research_evidence_bundle.md" in text
    assert "docs/release/capability_matrix.md" in text
    assert "paper trading" in text
    assert "live trading" in text


def test_capability_matrix_lists_prohibited_capabilities() -> None:
    text = _CAPABILITY.read_text(encoding="utf-8").lower()
    for needle in (
        "strategy",
        "signal",
        "portfolio",
        "pnl",
        "orders",
        "brokers",
        "paper",
        "live",
        "vendor",
        "ai runtime",
    ):
        assert needle in text
    assert "explicitly prohibited" in text


def test_command_docs_do_not_contain_database_url() -> None:
    text = _COMMANDS.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "postgresql+psycopg://" not in lowered
    assert "quant_dev_only_not_for_production" not in lowered
    assert "DATABASE_URL=" not in text
    assert "://quant:" not in lowered


def test_risk_register_contains_mitigations() -> None:
    text = _RISKS.read_text(encoding="utf-8").lower()
    assert "mitigation" in text
    assert "postgresql" in text
    assert "pnl" in text
    assert "evidence" in text


def test_final_checklist_mentions_venture_os_prompts() -> None:
    text = _CHECKLIST.read_text(encoding="utf-8")
    assert "AI_VENTURE_OS_PROMPTS" in text
    assert "/home/isma/invest" in text


def test_release_status_json_includes_freeze_fields(
    research_settings: Settings,
) -> None:
    report = build_release_status(settings=research_settings)
    payload = report.as_mapping()
    blob = json.dumps(payload, sort_keys=True)
    assert "DATABASE_URL" not in blob
    assert "postgresql+psycopg://" not in blob
    assert payload["kind"] == "research_release_status"
    assert payload["format_version"] == 2
    assert payload["final_freeze_ready"] is True
    assert payload["evidence_bundle_available"] is True
    assert payload["alembic_head_expected"] == EXPECTED_ALEMBIC_HEAD
    disabled = payload["capabilities"]["disabled"]
    assert isinstance(disabled, list)
    assert "paper_trading" in disabled
    assert "live_trading" in disabled
    assert "brokers" in disabled
    assert "ai_runtime" in disabled
    assert evidence_bundle_available(_ROOT) is True
    assert (
        final_freeze_ready(
            repo_root=_ROOT,
            research_mode=True,
            alembic_heads=alembic_script_heads(_ROOT),
        )
        is True
    )
    assert (
        final_freeze_ready(
            repo_root=_ROOT,
            research_mode=False,
            alembic_heads=alembic_script_heads(_ROOT),
        )
        is False
    )
