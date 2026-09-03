"""PostgreSQL tests for the normalized-dataset catalog. Metadata only."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from quant_platform.core.config import Settings, clear_settings_cache, get_settings
from quant_platform.data.models import NormalizedDatasetRecord
from quant_platform.data.repository import (
    create_corporate_action,
    create_ingestion_run,
    get_daily_bars,
    insert_daily_bars,
    upsert_data_source,
    upsert_instrument,
)
from quant_platform.data.validation import DailyBarDraft
from quant_platform.research.normalization import (
    AdjustmentMode,
    build_normalization_request,
    build_normalized_daily_bars_dataset,
    build_normalized_dataset_catalog_filters,
    build_normalized_dataset_registration,
    compare_normalized_datasets,
    evaluate_normalized_dataset_usability,
    get_normalized_dataset_by_id,
    list_normalized_datasets,
    register_normalized_dataset,
    write_normalized_dataset_artifacts,
)
from quant_platform.research.normalization.errors import (
    NormalizationError,
    NormalizationErrorCode,
)
from quant_platform.simulation.constructs import FORBIDDEN_TABLE_NAMES
from quant_platform.storage.database import list_public_tables

pytestmark = pytest.mark.postgres

ROOT = Path(__file__).resolve().parents[2]
_CATALOG_TABLES = frozenset({"normalized_datasets"})
_TRADING_TABLES = FORBIDDEN_TABLE_NAMES | {
    "portfolio",
    "trades",
    "orders",
    "fills",
    "signals",
    "strategies",
    "positions",
}
_SCRIPTS = ROOT / "scripts"


def _load_script(filename: str):
    path = _SCRIPTS / filename
    spec = importlib.util.spec_from_file_location(filename.replace("-", "_"), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:8]}"


def _draft(symbol: str, *, day: int, available_day: int, close: str) -> DailyBarDraft:
    price = Decimal(close)
    return DailyBarDraft(
        symbol=symbol,
        observation_time=datetime(2024, 1, day, tzinfo=UTC),
        available_time=datetime(2024, 1, available_day, tzinfo=UTC),
        open=price,
        high=price + Decimal("1"),
        low=price - Decimal("1"),
        close=price,
        volume=Decimal("100"),
    )


def _seed_split(
    session: Session,
    *,
    symbol: str,
    source_name: str,
) -> object:
    source = upsert_data_source(session, name=source_name, vendor="local_csv")
    instrument = upsert_instrument(session, symbol=symbol, asset_class="equity")
    run = create_ingestion_run(session, source_id=source.id)
    insert_daily_bars(
        session,
        drafts=[_draft(symbol, day=2, available_day=3, close="40")],
        instruments_by_symbol={symbol: instrument},
        source_id=source.id,
        ingestion_run_id=run.id,
    )
    create_corporate_action(
        session,
        instrument_id=instrument.id,
        action_type="split",
        effective_time=datetime(2024, 1, 10, tzinfo=UTC),
        available_time=datetime(2024, 1, 1, 20, tzinfo=UTC),
        quantity_before=Decimal("1"),
        quantity_after=Decimal("4"),
    )
    return instrument


def _build_registered(
    session: Session,
    tmp_path: Path,
    *,
    symbol: str,
    source_name: str,
    catalog_id: str | None = None,
    deterministic_id: bool = False,
    notes: str | None = None,
):
    request = build_normalization_request(
        as_of=datetime(2024, 1, 20, tzinfo=UTC),
        start_time=datetime(2024, 1, 1, tzinfo=UTC),
        end_time=datetime(2024, 1, 5, tzinfo=UTC),
        source_name=source_name,
        symbols=[symbol],
        adjustment_mode=AdjustmentMode.SPLIT_ONLY,
    )
    dataset = build_normalized_daily_bars_dataset(session, request)
    output = tmp_path / (catalog_id or "normalized")
    manifest = write_normalized_dataset_artifacts(dataset, output)
    entry = build_normalized_dataset_registration(
        dataset,
        manifest,
        normalized_dataset_id=catalog_id,
        deterministic_id=deterministic_id,
        notes=notes,
    )
    return register_normalized_dataset(session, entry), dataset, output


def test_catalog_revision_downgrade_and_upgrade(postgres_engine: Engine) -> None:
    clear_settings_cache()
    cfg = Config(str(ROOT / "alembic.ini"))
    try:
        command.downgrade(cfg, "0009_backtest_experiments")
        inspect(postgres_engine).clear_cache()
        tables = set(list_public_tables(postgres_engine))
        assert tables.isdisjoint(_CATALOG_TABLES)
    finally:
        command.upgrade(cfg, "head")
        inspect(postgres_engine).clear_cache()
    tables = set(list_public_tables(postgres_engine))
    assert _CATALOG_TABLES <= tables
    assert tables.isdisjoint(_TRADING_TABLES)
    assert "normalized_daily_bars" not in tables
    assert "normalized_bars" not in tables


def test_register_upserts_and_lists_usable(db_session: Session, tmp_path: Path) -> None:
    symbol = _unique("CAT")
    source_name = _unique("src")
    _seed_split(db_session, symbol=symbol, source_name=source_name)
    first, _dataset, _output = _build_registered(
        db_session,
        tmp_path,
        symbol=symbol,
        source_name=source_name,
        catalog_id="nd-upsert",
        notes="first",
    )
    assert first.action == "insert"
    assert first.entry.is_usable is True
    again, _dataset, _output = _build_registered(
        db_session,
        tmp_path,
        symbol=symbol,
        source_name=source_name,
        catalog_id="nd-upsert",
        notes="updated",
    )
    assert again.action == "update"
    listed = list_normalized_datasets(
        db_session,
        build_normalized_dataset_catalog_filters(usable_only=True),
    )
    assert any(item.normalized_dataset_id == "nd-upsert" for item in listed)
    loaded = get_normalized_dataset_by_id(db_session, "nd-upsert")
    assert loaded is not None
    assert loaded.notes == "updated"


def test_register_same_manifest_hash_different_id_conflicts(
    db_session: Session, tmp_path: Path
) -> None:
    symbol = _unique("CNF")
    source_name = _unique("src")
    _seed_split(db_session, symbol=symbol, source_name=source_name)
    first, dataset, output = _build_registered(
        db_session,
        tmp_path,
        symbol=symbol,
        source_name=source_name,
        catalog_id="nd-left",
    )
    manifest = write_normalized_dataset_artifacts(dataset, output / "again")
    other = build_normalized_dataset_registration(
        dataset,
        manifest,
        normalized_dataset_id="nd-right",
    )
    assert other.manifest_hash == first.entry.manifest_hash
    with pytest.raises(NormalizationError) as exc:
        register_normalized_dataset(db_session, other)
    assert exc.value.code == NormalizationErrorCode.CATALOG_CONFLICT


def test_check_usability_ok_and_fails_when_artifact_missing(
    db_session: Session, tmp_path: Path
) -> None:
    symbol = _unique("USE")
    source_name = _unique("src")
    _seed_split(db_session, symbol=symbol, source_name=source_name)
    registration, _dataset, output = _build_registered(
        db_session,
        tmp_path,
        symbol=symbol,
        source_name=source_name,
        catalog_id="nd-usable",
    )
    ok = evaluate_normalized_dataset_usability(
        db_session, registration.entry.normalized_dataset_id, output
    )
    assert ok.usable is True
    missing = evaluate_normalized_dataset_usability(
        db_session, registration.entry.normalized_dataset_id, tmp_path / "absent"
    )
    assert missing.usable is False
    assert any(item.code == "missing_artifact" for item in missing.issues)


def test_compare_same_and_different(db_session: Session, tmp_path: Path) -> None:
    symbol = _unique("CMP")
    source_name = _unique("src")
    _seed_split(db_session, symbol=symbol, source_name=source_name)
    left, _dataset, _output = _build_registered(
        db_session,
        tmp_path,
        symbol=symbol,
        source_name=source_name,
        catalog_id="nd-cmp-left",
    )
    right_same = get_normalized_dataset_by_id(db_session, "nd-cmp-left")
    assert right_same is not None
    identical = compare_normalized_datasets(left.entry, right_same)
    assert identical.verdict == "identical"

    other_symbol = _unique("CMO")
    other_source = _unique("src")
    _seed_split(db_session, symbol=other_symbol, source_name=other_source)
    right, _dataset, _output = _build_registered(
        db_session,
        tmp_path / "other",
        symbol=other_symbol,
        source_name=other_source,
        catalog_id="nd-cmp-right",
    )
    drifted = compare_normalized_datasets(left.entry, right.entry)
    assert drifted.verdict == "different"


def test_build_script_register(
    db_session: Session, tmp_path: Path, research_settings: Settings
) -> None:
    del research_settings
    symbol = _unique("SCR")
    source_name = _unique("src")
    _seed_split(db_session, symbol=symbol, source_name=source_name)
    db_session.commit()
    output = tmp_path / "script-out"
    builder = _load_script("build-normalized-dataset.py")
    code = builder.main(
        [
            "--source-name",
            source_name,
            "--symbol",
            symbol,
            "--start",
            "2024-01-01T00:00:00+00:00",
            "--end",
            "2024-01-05T00:00:00+00:00",
            "--as-of",
            "2024-01-20T00:00:00+00:00",
            "--output-dir",
            str(output),
            "--register",
            "--normalized-dataset-id",
            "nd-script",
            "--notes",
            "script-register",
            "--json",
        ]
    )
    assert code == 0
    loaded = get_normalized_dataset_by_id(db_session, "nd-script")
    assert loaded is not None
    assert loaded.notes == "script-register"
    row = db_session.scalars(
        select(NormalizedDatasetRecord).where(
            NormalizedDatasetRecord.normalized_dataset_id == "nd-script"
        )
    ).one()
    db_session.delete(row)
    db_session.commit()


def test_raw_daily_bars_unchanged_after_register(
    db_session: Session, tmp_path: Path
) -> None:
    symbol = _unique("RAW")
    source_name = _unique("src")
    instrument = _seed_split(db_session, symbol=symbol, source_name=source_name)
    before = [
        (row.id, row.close, row.volume, row.available_time)
        for row in get_daily_bars(db_session, instrument_id=instrument.id)
    ]
    _build_registered(
        db_session,
        tmp_path,
        symbol=symbol,
        source_name=source_name,
        catalog_id="nd-raw",
    )
    after = [
        (row.id, row.close, row.volume, row.available_time)
        for row in get_daily_bars(db_session, instrument_id=instrument.id)
    ]
    assert after == before


def test_catalog_has_no_trading_tables_and_research_mode(
    postgres_engine: Engine,
) -> None:
    settings = get_settings()
    assert settings.app_mode == "research"
    assert settings.is_research_mode is True
    tables = set(list_public_tables(postgres_engine))
    assert "normalized_datasets" in tables
    assert "normalized_daily_bars" not in tables
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
