"""PostgreSQL end-to-end research evidence bundle. No trading tables."""

from __future__ import annotations

import csv
import json
import shutil
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from quant_platform.core.config import get_settings
from quant_platform.release.checks import run_research_release_checks
from quant_platform.release.constants import EXPECTED_ALEMBIC_HEAD
from quant_platform.release.evidence_bundle import build_research_evidence_bundle
from quant_platform.release.evidence_integrity import verify_research_evidence_bundle
from quant_platform.release.evidence_types import (
    NORMALIZED_DATASET_DIRNAME,
    ResearchEvidenceBundleRequest,
)
from quant_platform.research.normalization import (
    evaluate_normalized_dataset_usability,
    get_normalized_dataset_by_id,
)
from quant_platform.research.normalization.integrity import (
    verify_normalization_artifacts,
)
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
    assert manifest.fixture_data_mode == "inserted"
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


def test_evidence_bundle_include_normalized_dataset(
    db_session: Session, tmp_path: Path, postgres_engine: Engine
) -> None:
    request = _request(tmp_path, include_normalized_dataset=True)
    result = build_research_evidence_bundle(db_session, request)
    assert result.ok is True
    assert result.manifest.normalized_dataset_hash
    assert result.manifest.normalized_dataset_hash.startswith("sha256:")
    assert result.manifest.normalized_dataset_id is None
    step_names = [item.name for item in result.manifest.steps]
    assert "normalization" in step_names
    norm_dir = result.output_dir / NORMALIZED_DATASET_DIRNAME
    assert (norm_dir / "normalized_daily_bars.csv").is_file()
    integrity = verify_normalization_artifacts(norm_dir)
    assert integrity.ok is True
    report = verify_research_evidence_bundle(result.output_dir)
    assert report.ok is True
    raw_closes = _raw_daily_bar_closes(db_session, request.fixture_dir)
    fixture_closes = _fixture_closes(request.fixture_dir)
    assert raw_closes == fixture_closes
    settings = get_settings()
    assert settings.app_mode == "research"
    assert settings.is_research_mode is True
    tables = set(list_public_tables(postgres_engine))
    for name in (
        "strategies",
        "signals",
        "orders",
        "portfolio",
        "trades",
        "fills",
    ):
        assert name not in tables
        assert name not in _TRADING_TABLES.intersection(tables)


def test_evidence_bundle_register_normalized_dataset_includes_id(
    db_session: Session, tmp_path: Path
) -> None:
    request = _request(
        tmp_path,
        include_normalized_dataset=True,
        register_normalized_dataset=True,
    )
    result = build_research_evidence_bundle(db_session, request)
    assert result.ok is True
    assert result.manifest.normalized_dataset_hash
    assert result.manifest.normalized_dataset_id
    payload = result.manifest.as_mapping()
    assert payload.get("normalized_dataset_id") == result.manifest.normalized_dataset_id
    row = get_normalized_dataset_by_id(
        db_session, result.manifest.normalized_dataset_id
    )
    assert row is not None
    assert row.source_type == "snapshot"
    usability = evaluate_normalized_dataset_usability(
        db_session,
        result.manifest.normalized_dataset_id,
        result.output_dir / NORMALIZED_DATASET_DIRNAME,
    )
    assert usability.usable is True


def test_evidence_bundle_default_omits_normalized_dataset(
    db_session: Session, tmp_path: Path
) -> None:
    request = _request(tmp_path)
    result = build_research_evidence_bundle(db_session, request)
    assert result.ok is True
    assert result.manifest.normalized_dataset_hash is None
    assert result.manifest.normalized_dataset_id is None
    step_names = [item.name for item in result.manifest.steps]
    assert "normalization" not in step_names
    assert not (result.output_dir / NORMALIZED_DATASET_DIRNAME).exists()


def test_evidence_bundle_release_check_stays_green(
    db_session: Session, research_settings
) -> None:
    report = run_research_release_checks(
        settings=research_settings,
        skip_compose=True,
        skip_regression=True,
        skip_imports=True,
    )
    assert report.ok is True
    names = {item.name: item.status for item in report.checks}
    assert names.get("normalization_regression") == "ok"
    assert report.app_mode == "research"


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


def test_evidence_bundle_second_run_fails_without_reuse_flag(
    db_session: Session, tmp_path: Path
) -> None:
    first = _request(tmp_path / "first")
    inserted = build_research_evidence_bundle(db_session, first)
    assert inserted.ok is True
    assert inserted.manifest.fixture_data_mode == "inserted"
    second = ResearchEvidenceBundleRequest(
        fixture_dir=first.fixture_dir,
        output_dir=tmp_path / "second",
        deterministic_id=True,
        created_at=_STAMP,
        git_commit=None,
        resolve_git=False,
        source_name=first.source_name,
        skip_compose=True,
        skip_regression=True,
        skip_release_db=True,
        allow_existing_fixture_data=False,
    )
    result = build_research_evidence_bundle(db_session, second)
    assert result.ok is False
    codes = {item.code for item in result.manifest.errors}
    assert "ingest_failed" in codes
    assert result.manifest.fixture_data_mode == "failed"


def test_evidence_bundle_second_run_reuses_matching_fixtures(
    db_session: Session, tmp_path: Path, postgres_engine: Engine
) -> None:
    first = _request(tmp_path / "first")
    inserted = build_research_evidence_bundle(db_session, first)
    assert inserted.ok is True
    before = _raw_daily_bar_state(db_session, first.fixture_dir, first.source_name)
    second = ResearchEvidenceBundleRequest(
        fixture_dir=first.fixture_dir,
        output_dir=tmp_path / "second",
        deterministic_id=True,
        created_at=_STAMP,
        git_commit=None,
        resolve_git=False,
        source_name=first.source_name,
        skip_compose=True,
        skip_regression=True,
        skip_release_db=True,
        allow_existing_fixture_data=True,
    )
    result = build_research_evidence_bundle(db_session, second)
    assert result.ok is True
    assert result.manifest.fixture_data_mode == "reused"
    assert result.manifest.fixture_reuse is not None
    assert result.manifest.fixture_reuse.reused_bar_count >= 1
    assert result.manifest.fixture_reuse.inserted_bar_count == 0
    after = _raw_daily_bar_state(db_session, first.fixture_dir, first.source_name)
    assert after == before
    settings = get_settings()
    assert settings.app_mode == "research"
    tables = set(list_public_tables(postgres_engine))
    for name in (
        "strategies",
        "signals",
        "orders",
        "portfolio",
        "trades",
        "fills",
    ):
        assert name not in tables
    report = verify_research_evidence_bundle(result.output_dir)
    assert report.ok is True


def test_evidence_bundle_reuse_fails_on_ohlcv_mismatch(
    db_session: Session, tmp_path: Path
) -> None:
    first = _request(tmp_path / "first")
    inserted = build_research_evidence_bundle(db_session, first)
    assert inserted.ok is True
    before = _raw_daily_bar_state(db_session, first.fixture_dir, first.source_name)
    mutated = tmp_path / "mutated"
    shutil.copytree(first.fixture_dir, mutated)
    _rewrite_csv_field(mutated / "daily_bars.csv", "close", "99.99")
    second = ResearchEvidenceBundleRequest(
        fixture_dir=mutated,
        output_dir=tmp_path / "second",
        deterministic_id=True,
        created_at=_STAMP,
        git_commit=None,
        resolve_git=False,
        source_name=first.source_name,
        skip_compose=True,
        skip_regression=True,
        skip_release_db=True,
        allow_existing_fixture_data=True,
    )
    result = build_research_evidence_bundle(db_session, second)
    assert result.ok is False
    codes = {item.code for item in result.manifest.errors}
    assert "fixture_reuse_mismatch" in codes
    after = _raw_daily_bar_state(db_session, first.fixture_dir, first.source_name)
    assert after == before


def test_evidence_bundle_reuse_fails_on_corporate_action_mismatch(
    db_session: Session, tmp_path: Path
) -> None:
    first = _request(tmp_path / "first")
    inserted = build_research_evidence_bundle(db_session, first)
    assert inserted.ok is True
    before = _raw_daily_bar_state(db_session, first.fixture_dir, first.source_name)
    mutated = tmp_path / "mutated"
    shutil.copytree(first.fixture_dir, mutated)
    _rewrite_csv_field(mutated / "corporate_actions.csv", "quantity_after", "9")
    second = ResearchEvidenceBundleRequest(
        fixture_dir=mutated,
        output_dir=tmp_path / "second",
        deterministic_id=True,
        created_at=_STAMP,
        git_commit=None,
        resolve_git=False,
        source_name=first.source_name,
        skip_compose=True,
        skip_regression=True,
        skip_release_db=True,
        allow_existing_fixture_data=True,
    )
    result = build_research_evidence_bundle(db_session, second)
    assert result.ok is False
    codes = {item.code for item in result.manifest.errors}
    assert "fixture_reuse_mismatch" in codes
    after = _raw_daily_bar_state(db_session, first.fixture_dir, first.source_name)
    assert after == before


def test_evidence_bundle_reuse_fails_on_session_mismatch(
    db_session: Session, tmp_path: Path
) -> None:
    first = _request(tmp_path / "first")
    inserted = build_research_evidence_bundle(db_session, first)
    assert inserted.ok is True
    before = _raw_daily_bar_state(db_session, first.fixture_dir, first.source_name)
    mutated = tmp_path / "mutated"
    shutil.copytree(first.fixture_dir, mutated)
    _rewrite_csv_field(mutated / "sessions.csv", "session_kind", "holiday")
    second = ResearchEvidenceBundleRequest(
        fixture_dir=mutated,
        output_dir=tmp_path / "second",
        deterministic_id=True,
        created_at=_STAMP,
        git_commit=None,
        resolve_git=False,
        source_name=first.source_name,
        skip_compose=True,
        skip_regression=True,
        skip_release_db=True,
        allow_existing_fixture_data=True,
    )
    result = build_research_evidence_bundle(db_session, second)
    assert result.ok is False
    codes = {item.code for item in result.manifest.errors}
    assert "fixture_reuse_mismatch" in codes
    after = _raw_daily_bar_state(db_session, first.fixture_dir, first.source_name)
    assert after == before


def test_evidence_bundle_normalized_dataset_works_with_reuse(
    db_session: Session, tmp_path: Path
) -> None:
    first = _request(
        tmp_path / "first",
        include_normalized_dataset=True,
        register_normalized_dataset=True,
    )
    inserted = build_research_evidence_bundle(db_session, first)
    assert inserted.ok is True
    second = ResearchEvidenceBundleRequest(
        fixture_dir=first.fixture_dir,
        output_dir=tmp_path / "second",
        deterministic_id=True,
        created_at=_STAMP,
        git_commit=None,
        resolve_git=False,
        source_name=first.source_name,
        skip_compose=True,
        skip_regression=True,
        skip_release_db=True,
        allow_existing_fixture_data=True,
        include_normalized_dataset=True,
        register_normalized_dataset=True,
    )
    result = build_research_evidence_bundle(db_session, second)
    assert result.ok is True
    assert result.manifest.fixture_data_mode == "reused"
    assert result.manifest.normalized_dataset_hash
    assert result.manifest.normalized_dataset_id
    integrity = verify_normalization_artifacts(
        result.output_dir / NORMALIZED_DATASET_DIRNAME
    )
    assert integrity.ok is True
    raw_closes = _raw_daily_bar_closes(db_session, first.fixture_dir)
    fixture_closes = _fixture_closes(first.fixture_dir)
    assert raw_closes == fixture_closes


def _raw_daily_bar_state(
    session: Session, fixture_dir: Path, source_name: str | None
) -> tuple[tuple[object, ...], ...]:
    symbol = _fixture_symbol(fixture_dir)
    rows = session.execute(
        text(
            "SELECT b.id, b.observation_time, b.available_time, "
            "b.open, b.high, b.low, b.close, b.volume, b.is_correction "
            "FROM daily_bars AS b "
            "JOIN instruments AS i ON i.id = b.instrument_id "
            "JOIN data_sources AS s ON s.id = b.source_id "
            "WHERE i.symbol = :symbol AND s.name = :source_name "
            "ORDER BY b.observation_time, b.available_time, b.id"
        ),
        {"symbol": symbol, "source_name": source_name},
    ).all()
    return tuple(tuple(item) for item in rows)


def _rewrite_csv_field(path: Path, field: str, value: str) -> None:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        names = list(reader.fieldnames or [])
        rows = list(reader)
    if field not in names:
        raise AssertionError(f"missing column {field}")
    changed = False
    for row in rows:
        if (row.get(field) or "") == value:
            continue
        row[field] = value
        if field == "session_kind" and value == "holiday":
            if "open_time" in names:
                row["open_time"] = ""
            if "close_time" in names:
                row["close_time"] = ""
        changed = True
        break
    if not changed:
        raise AssertionError(f"could not change {field}")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=names)
        writer.writeheader()
        writer.writerows(rows)


def _raw_daily_bar_closes(
    session: Session, fixture_dir: Path
) -> tuple[tuple[str, Decimal], ...]:
    symbol = _fixture_symbol(fixture_dir)
    rows = session.execute(
        text(
            "SELECT b.observation_time, b.close "
            "FROM daily_bars AS b "
            "JOIN instruments AS i ON i.id = b.instrument_id "
            "WHERE i.symbol = :symbol AND b.is_correction = false "
            "ORDER BY b.observation_time, b.close"
        ),
        {"symbol": symbol},
    ).all()
    return tuple((_observation_day(item[0]), Decimal(str(item[1]))) for item in rows)


def _fixture_closes(fixture_dir: Path) -> tuple[tuple[str, Decimal], ...]:
    path = fixture_dir / "daily_bars.csv"
    rows: list[tuple[str, Decimal]] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            rows.append((row["date"].strip(), Decimal(row["close"])))
    return tuple(sorted(rows, key=lambda item: item[0]))


def _fixture_symbol(fixture_dir: Path) -> str:
    with (fixture_dir / "daily_bars.csv").open(newline="", encoding="utf-8") as handle:
        first = next(csv.DictReader(handle))
    return first["symbol"].strip()


def _observation_day(value: object) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    return str(value)[:10]
