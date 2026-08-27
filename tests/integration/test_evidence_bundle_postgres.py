"""PostgreSQL end-to-end research evidence bundle. No trading tables."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from quant_platform.core.config import get_settings
from quant_platform.release.constants import EXPECTED_ALEMBIC_HEAD
from quant_platform.release.evidence_bundle import build_research_evidence_bundle
from quant_platform.release.evidence_integrity import verify_research_evidence_bundle
from quant_platform.release.evidence_types import ResearchEvidenceBundleRequest
from quant_platform.simulation.constructs import FORBIDDEN_TABLE_NAMES
from quant_platform.storage.database import list_public_tables

pytestmark = pytest.mark.postgres

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "e2e_research_bundle"
_STAMP = datetime(2024, 6, 1, tzinfo=UTC)
_TRADING_TABLES = FORBIDDEN_TABLE_NAMES | {"portfolio"}


def _token(prefix: str, size: int) -> str:
    return f"{prefix}{uuid4().hex[:size]}"


def _unique_fixtures(tmp_path: Path) -> Path:
    dest = tmp_path / "fixtures"
    shutil.copytree(FIXTURES, dest)
    symbol = _token("S", 7)
    exchange = _token("X", 7)
    calendar = _token("C", 8)
    for path in dest.iterdir():
        text = path.read_text(encoding="utf-8")
        path.write_text(
            text.replace("E2E_EQUITY", calendar)
            .replace("E2EA", symbol)
            .replace("XE2E", exchange),
            encoding="utf-8",
        )
    return dest


def _request(tmp_path: Path, **overrides: object) -> ResearchEvidenceBundleRequest:
    payload: dict[str, object] = {
        "fixture_dir": _unique_fixtures(tmp_path),
        "output_dir": tmp_path / "bundle",
        "deterministic_id": True,
        "created_at": _STAMP,
        "git_commit": None,
        "resolve_git": False,
        "source_name": _token("src", 8),
        "skip_compose": True,
        "skip_regression": True,
        "skip_release_db": True,
    }
    payload.update(overrides)
    return ResearchEvidenceBundleRequest(**payload)  # type: ignore[arg-type]


def test_build_research_evidence_bundle_end_to_end(
    db_session: Session, tmp_path: Path
) -> None:
    request = _request(tmp_path)
    result = build_research_evidence_bundle(db_session, request)
    assert result.ok is True
    manifest = result.manifest
    assert manifest.dataset_snapshot_id
    assert manifest.replay_id
    assert manifest.backtest_id
    assert manifest.experiment_id
    assert manifest.replay_ready is True
    assert manifest.backtest_usable is True
    assert manifest.experiment_usable is True
    assert manifest.release_ok is True
    assert manifest.alembic_head == EXPECTED_ALEMBIC_HEAD
    assert manifest.app_mode == "research"
    blob = json.dumps(manifest.as_mapping(), sort_keys=True)
    assert "DATABASE_URL" not in blob
    assert "postgresql+psycopg://" not in blob
    report = verify_research_evidence_bundle(result.output_dir)
    assert report.ok is True
    assert report.bundle_hash == manifest.bundle_hash


def test_evidence_bundle_fails_when_app_mode_is_not_research(
    db_session: Session, tmp_path: Path
) -> None:
    request = _request(tmp_path, research_mode=False)
    result = build_research_evidence_bundle(db_session, request)
    assert result.ok is False
    codes = {item.code for item in result.manifest.errors}
    assert "app_mode_not_research" in codes
    assert result.manifest.dataset_snapshot_id is None


def test_evidence_bundle_has_no_trading_tables(postgres_engine: Engine) -> None:
    tables = set(list_public_tables(postgres_engine))
    assert tables.isdisjoint(_TRADING_TABLES)
    inspector = inspect(postgres_engine)
    names = set(inspector.get_table_names())
    for name in (
        "strategies",
        "signals",
        "orders",
        "portfolio",
        "trades",
        "fills",
    ):
        assert name not in names
        assert name not in tables


def test_evidence_bundle_alembic_head_matches_expected(
    postgres_engine: Engine,
) -> None:
    settings = get_settings()
    assert settings.is_research_mode is True
    with postgres_engine.connect() as connection:
        head = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar()
    assert head == EXPECTED_ALEMBIC_HEAD
