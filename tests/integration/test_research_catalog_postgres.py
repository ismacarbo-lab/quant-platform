"""PostgreSQL dataset snapshot catalog."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from quant_platform.core.config import clear_settings_cache
from quant_platform.data.repository import (
    create_ingestion_run,
    insert_daily_bars,
    upsert_data_source,
    upsert_instrument,
)
from quant_platform.data.validation import DailyBarDraft
from quant_platform.research.catalog import (
    compare_dataset_snapshots,
    get_dataset_snapshot_by_id,
    get_dataset_snapshot_by_manifest_hash,
    list_dataset_snapshots,
    register_dataset_snapshot,
)
from quant_platform.research.catalog_types import build_dataset_snapshot_catalog_filters
from quant_platform.research.errors import DatasetErrorCode, DatasetValidationError
from quant_platform.research.snapshot_types import (
    DatasetSnapshotManifest,
    SnapshotArtifact,
    build_dataset_snapshot_request,
)
from quant_platform.research.snapshots import create_daily_bars_snapshot
from quant_platform.storage.database import list_public_tables

pytestmark = pytest.mark.postgres

ROOT = Path(__file__).resolve().parents[2]
_CATALOG_TABLES = frozenset({"dataset_snapshots"})
_TRADING_TABLES = frozenset(
    {"trades", "orders", "fills", "signals", "strategies", "positions"}
)


def _digest(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode("utf-8")).hexdigest()


def _artifacts() -> tuple[SnapshotArtifact, ...]:
    return (
        SnapshotArtifact(name="daily_bars", path="daily_bars.csv", kind="csv"),
        SnapshotArtifact(name="quality_report", path="quality.json", kind="json"),
        SnapshotArtifact(name="manifest", path="manifest.json", kind="json"),
    )


def _manifest(**overrides: object) -> DatasetSnapshotManifest:
    values: dict[str, object] = {
        "snapshot_id": uuid4(),
        "created_at": datetime(2024, 1, 10, tzinfo=UTC),
        "package_version": "0.1.0",
        "git_commit": "abc123",
        "dataset_request": {
            "as_of": "2024-01-10T00:00:00.000000Z",
            "start_time": "2024-01-01T00:00:00.000000Z",
            "end_time": "2024-01-05T00:00:00.000000Z",
            "symbols": ["FICT"],
        },
        "quality_request": {"as_of": "2024-01-10T00:00:00.000000Z"},
        "row_count": 1,
        "instrument_count": 1,
        "error_count": 0,
        "warning_count": 1,
        "info_count": 0,
        "content_hash": _digest("content-ok"),
        "quality_hash": _digest("quality-ok"),
        "manifest_hash": _digest(str(uuid4())),
        "artifacts": _artifacts(),
        "notes": "catalog-test",
    }
    values.update(overrides)
    return DatasetSnapshotManifest(**values)  # type: ignore[arg-type]


def test_catalog_revision_downgrade_and_upgrade(postgres_engine: Engine) -> None:
    clear_settings_cache()
    cfg = Config(str(ROOT / "alembic.ini"))
    try:
        command.downgrade(cfg, "0004_master")
        inspect(postgres_engine).clear_cache()
        tables = set(list_public_tables(postgres_engine))
        assert tables.isdisjoint(_CATALOG_TABLES)
    finally:
        command.upgrade(cfg, "head")
        inspect(postgres_engine).clear_cache()
    tables = set(list_public_tables(postgres_engine))
    assert _CATALOG_TABLES <= tables
    assert tables.isdisjoint(_TRADING_TABLES)


def test_register_snapshot_upserts_and_filters(db_session: Session) -> None:
    first = _manifest(content_hash=_digest("same-content"), notes="first")
    inserted = register_dataset_snapshot(db_session, first)
    assert inserted.action == "insert"
    assert inserted.entry.is_usable is True
    again = register_dataset_snapshot(db_session, first)
    assert again.action == "update"
    listed = list_dataset_snapshots(
        db_session,
        build_dataset_snapshot_catalog_filters(content_hash=first.content_hash),
    )
    assert len(listed) == 1
    by_id = get_dataset_snapshot_by_id(db_session, str(first.snapshot_id))
    by_hash = get_dataset_snapshot_by_manifest_hash(db_session, first.manifest_hash)
    assert by_id is not None and by_hash is not None
    assert by_id.snapshot_id == by_hash.snapshot_id

    broken = _manifest(
        content_hash=_digest("other-content"),
        error_count=3,
        dataset_request={
            "as_of": "2024-01-10T00:00:00.000000Z",
            "start_time": "2024-01-01T00:00:00.000000Z",
            "end_time": "2024-01-05T00:00:00.000000Z",
            "symbols": ["ZZZZ"],
        },
    )
    register_dataset_snapshot(db_session, broken)
    usable = list_dataset_snapshots(
        db_session, build_dataset_snapshot_catalog_filters(usable_only=True)
    )
    assert all(item.is_usable for item in usable)
    assert str(broken.snapshot_id) not in {item.snapshot_id for item in usable}
    by_symbol = list_dataset_snapshots(
        db_session, build_dataset_snapshot_catalog_filters(symbol="FICT")
    )
    assert str(first.snapshot_id) in {item.snapshot_id for item in by_symbol}
    comparison = compare_dataset_snapshots(first, broken)
    assert comparison.same_content_hash is False
    assert comparison.error_count_delta == 3


def test_register_same_manifest_hash_different_id_conflicts(
    db_session: Session,
) -> None:
    digest = _digest("shared-manifest")
    register_dataset_snapshot(db_session, _manifest(manifest_hash=digest))
    with pytest.raises(DatasetValidationError) as exc:
        register_dataset_snapshot(db_session, _manifest(manifest_hash=digest))
    assert exc.value.code == DatasetErrorCode.CATALOG_CONFLICT


def test_create_snapshot_then_register(db_session: Session, tmp_path: Path) -> None:
    source = upsert_data_source(
        db_session, name=f"src_{uuid4().hex[:8]}", vendor="local_csv"
    )
    instrument = upsert_instrument(
        db_session, symbol=f"CAT_{uuid4().hex[:8]}", asset_class="equity"
    )
    run = create_ingestion_run(db_session, source_id=source.id)
    price = Decimal("10")
    insert_daily_bars(
        db_session,
        drafts=[
            DailyBarDraft(
                symbol=instrument.symbol,
                observation_time=datetime(2024, 1, 2, tzinfo=UTC),
                available_time=datetime(2024, 1, 3, tzinfo=UTC),
                open=price,
                high=price + Decimal("1"),
                low=price - Decimal("1"),
                close=price,
                volume=price,
            )
        ],
        instruments_by_symbol={instrument.symbol: instrument},
        source_id=source.id,
        ingestion_run_id=run.id,
    )
    request = build_dataset_snapshot_request(
        as_of=datetime(2024, 1, 10, tzinfo=UTC),
        start_time=datetime(2024, 1, 1, tzinfo=UTC),
        end_time=datetime(2024, 1, 5, tzinfo=UTC),
        symbols=[instrument.symbol],
    )
    result = create_daily_bars_snapshot(
        db_session,
        request,
        tmp_path / "snap",
        created_at=datetime(2024, 1, 10, tzinfo=UTC),
        resolve_git=False,
    )
    registration = register_dataset_snapshot(
        db_session, result.manifest, base_path=tmp_path / "snap"
    )
    assert registration.action == "insert"
    assert registration.entry.row_count == 1
    loaded = get_dataset_snapshot_by_id(db_session, str(result.manifest.snapshot_id))
    assert loaded is not None
