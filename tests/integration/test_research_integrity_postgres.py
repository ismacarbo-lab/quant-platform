"""PostgreSQL catalog integrity checks against local snapshot folders."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from quant_platform.data.repository import (
    create_ingestion_run,
    insert_daily_bars,
    upsert_data_source,
    upsert_instrument,
)
from quant_platform.data.validation import DailyBarDraft
from quant_platform.release.constants import EXPECTED_PUBLIC_TABLES
from quant_platform.research.catalog import (
    compare_catalog_snapshots,
    register_dataset_snapshot,
)
from quant_platform.research.catalog_integrity import (
    verify_catalog,
    verify_catalog_entry_artifacts,
    verify_snapshot_artifacts,
)
from quant_platform.research.integrity_types import IntegrityIssueCode
from quant_platform.research.snapshot_types import build_dataset_snapshot_request
from quant_platform.research.snapshots import create_daily_bars_snapshot
from quant_platform.storage.database import list_public_tables

pytestmark = pytest.mark.postgres

_TRADING_TABLES = frozenset(
    {"trades", "orders", "fills", "signals", "strategies", "positions"}
)
_ALLOWED = EXPECTED_PUBLIC_TABLES


def _seed_snapshot(session: Session, output_dir: Path, symbol: str | None = None):
    source = upsert_data_source(
        session, name=f"src_{uuid4().hex[:8]}", vendor="local_csv"
    )
    instrument = upsert_instrument(
        session, symbol=symbol or f"INT_{uuid4().hex[:8]}", asset_class="equity"
    )
    run = create_ingestion_run(session, source_id=source.id)
    price = Decimal("10")
    insert_daily_bars(
        session,
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
    return create_daily_bars_snapshot(
        session,
        request,
        output_dir,
        created_at=datetime(2024, 1, 10, tzinfo=UTC),
        resolve_git=False,
    )


def test_register_and_verify_catalog_entry(db_session: Session, tmp_path: Path) -> None:
    result = _seed_snapshot(db_session, tmp_path / "snap")
    register_dataset_snapshot(db_session, result.manifest)
    report = verify_catalog_entry_artifacts(
        db_session, str(result.manifest.snapshot_id), tmp_path / "snap"
    )
    assert report.ok is True
    assert report.error_count == 0
    assert report.recomputed_content_hash == result.manifest.content_hash


def test_verify_detects_missing_artifact(db_session: Session, tmp_path: Path) -> None:
    result = _seed_snapshot(db_session, tmp_path / "snap")
    register_dataset_snapshot(db_session, result.manifest)
    (tmp_path / "snap" / "daily_bars.csv").unlink()
    report = verify_catalog_entry_artifacts(
        db_session, str(result.manifest.snapshot_id), tmp_path / "snap"
    )
    assert report.ok is False
    assert IntegrityIssueCode.MISSING_ARTIFACT.value in {
        item.code for item in report.issues
    }


def test_verify_detects_catalog_manifest_mismatch(
    db_session: Session, tmp_path: Path
) -> None:
    result = _seed_snapshot(db_session, tmp_path / "snap")
    register_dataset_snapshot(db_session, result.manifest)
    manifest_path = tmp_path / "snap" / "manifest.json"
    text = manifest_path.read_text(encoding="utf-8")
    manifest_path.write_text(
        text.replace(result.manifest.content_hash, "sha256:" + "d" * 64),
        encoding="utf-8",
    )
    report = verify_catalog_entry_artifacts(
        db_session, str(result.manifest.snapshot_id), tmp_path / "snap"
    )
    assert report.ok is False
    codes = {item.code for item in report.issues}
    assert IntegrityIssueCode.CATALOG_MANIFEST_MISMATCH.value in codes


def test_verify_catalog_filters_snapshot_id(
    db_session: Session, tmp_path: Path
) -> None:
    first = _seed_snapshot(db_session, tmp_path / "one")
    second = _seed_snapshot(db_session, tmp_path / "two")
    register_dataset_snapshot(db_session, first.manifest)
    register_dataset_snapshot(db_session, second.manifest)
    report = verify_catalog(
        db_session, tmp_path, snapshot_id=str(first.manifest.snapshot_id)
    )
    assert report.entry_count == 1
    assert report.reports[0].snapshot_id == str(first.manifest.snapshot_id)
    assert report.ok is True


def test_verify_several_snapshots(db_session: Session, tmp_path: Path) -> None:
    first = _seed_snapshot(db_session, tmp_path / "one")
    second = _seed_snapshot(db_session, tmp_path / "two")
    register_dataset_snapshot(db_session, first.manifest)
    register_dataset_snapshot(db_session, second.manifest)
    first_report = verify_catalog_entry_artifacts(
        db_session, str(first.manifest.snapshot_id), tmp_path
    )
    second_report = verify_catalog_entry_artifacts(
        db_session, str(second.manifest.snapshot_id), tmp_path
    )
    assert first_report.ok is True
    assert second_report.ok is True


def test_compare_cataloged_snapshots(db_session: Session, tmp_path: Path) -> None:
    first = _seed_snapshot(db_session, tmp_path / "one")
    second = _seed_snapshot(db_session, tmp_path / "two")
    register_dataset_snapshot(db_session, first.manifest)
    register_dataset_snapshot(db_session, second.manifest)
    comparison = compare_catalog_snapshots(
        db_session, str(first.manifest.snapshot_id), str(second.manifest.snapshot_id)
    )
    assert comparison.same_manifest_hash is False
    assert comparison.snapshot_a_id == str(first.manifest.snapshot_id)


def test_integrity_does_not_create_tables(
    db_session: Session, postgres_engine: Engine, tmp_path: Path
) -> None:
    before = set(list_public_tables(postgres_engine))
    result = _seed_snapshot(db_session, tmp_path / "snap")
    register_dataset_snapshot(db_session, result.manifest)
    verify_snapshot_artifacts(tmp_path / "snap")
    verify_catalog_entry_artifacts(
        db_session, str(result.manifest.snapshot_id), tmp_path / "snap"
    )
    after = set(list_public_tables(postgres_engine))
    assert after == before
    assert after <= _ALLOWED
    assert after.isdisjoint(_TRADING_TABLES)
