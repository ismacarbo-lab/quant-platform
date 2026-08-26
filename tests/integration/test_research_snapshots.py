"""PostgreSQL dataset snapshots (CSV, quality JSON, manifest, hashes)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from quant_platform.data.models import Instrument
from quant_platform.data.repository import (
    create_corporate_action,
    create_exchange,
    create_ingestion_run,
    get_daily_bars,
    insert_daily_bar_correction,
    insert_daily_bars,
    upsert_data_source,
    upsert_instrument,
)
from quant_platform.data.validation import DailyBarDraft
from quant_platform.research.snapshot_types import (
    DAILY_BARS_ARTIFACT_NAME,
    MANIFEST_ARTIFACT_NAME,
    QUALITY_ARTIFACT_NAME,
    build_dataset_snapshot_request,
)
from quant_platform.research.snapshots import create_daily_bars_snapshot
from quant_platform.storage.database import list_public_tables

pytestmark = pytest.mark.postgres

_RESEARCH_TABLES = frozenset(
    {
        "alembic_version",
        "corporate_actions",
        "daily_bars",
        "data_sources",
        "exchanges",
        "ingestion_errors",
        "ingestion_runs",
        "instrument_identifiers",
        "instruments",
        "market_calendars",
        "market_sessions",
        "raw_ingestion_records",
        "dataset_snapshots",
        "simulation_replay_runs",
        "backtest_runs",
        "backtest_experiments",
    }
)


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
        low=price - Decimal("1") if price >= 1 else Decimal("0"),
        close=price,
        volume=Decimal("100"),
    )


def _insert_bar(
    session: Session,
    *,
    instrument: Instrument,
    source_id: UUID,
    ingestion_run_id: UUID,
    day: int,
    available_day: int,
    close: str,
) -> None:
    insert_daily_bars(
        session,
        drafts=[
            _draft(instrument.symbol, day=day, available_day=available_day, close=close)
        ],
        instruments_by_symbol={instrument.symbol: instrument},
        source_id=source_id,
        ingestion_run_id=ingestion_run_id,
    )


def test_create_snapshot_writes_artifacts_and_stable_content_hash(
    db_session: Session,
    postgres_engine: Engine,
    tmp_path: Path,
) -> None:
    before = set(list_public_tables(postgres_engine))
    source = upsert_data_source(db_session, name=_unique("src"), vendor="local_csv")
    venue = create_exchange(db_session, code=_unique("XNAS"), timezone="UTC")
    instrument = upsert_instrument(
        db_session,
        symbol=_unique("SNAP"),
        asset_class="equity",
        exchange_id=venue.id,
        currency="USD",
    )
    run = create_ingestion_run(db_session, source_id=source.id)
    _insert_bar(
        db_session,
        instrument=instrument,
        source_id=source.id,
        ingestion_run_id=run.id,
        day=2,
        available_day=3,
        close="40",
    )
    create_corporate_action(
        db_session,
        instrument_id=instrument.id,
        action_type="split",
        effective_time=datetime(2024, 1, 2, tzinfo=UTC),
        available_time=datetime(2023, 12, 15, tzinfo=UTC),
        quantity_before=Decimal("1"),
        quantity_after=Decimal("4"),
        note="fictional",
    )
    request = build_dataset_snapshot_request(
        as_of=datetime(2024, 1, 10, tzinfo=UTC),
        start_time=datetime(2024, 1, 1, tzinfo=UTC),
        end_time=datetime(2024, 1, 5, tzinfo=UTC),
        symbols=[instrument.symbol],
        notes="unit fixture",
    )
    first_dir = tmp_path / "one"
    second_dir = tmp_path / "two"
    first = create_daily_bars_snapshot(
        db_session,
        request,
        first_dir,
        created_at=datetime(2024, 1, 10, tzinfo=UTC),
        resolve_git=False,
    )
    second = create_daily_bars_snapshot(
        db_session,
        request,
        second_dir,
        created_at=datetime(2024, 1, 11, tzinfo=UTC),
        resolve_git=False,
    )
    assert (first_dir / DAILY_BARS_ARTIFACT_NAME).is_file()
    assert (first_dir / QUALITY_ARTIFACT_NAME).is_file()
    assert (first_dir / MANIFEST_ARTIFACT_NAME).is_file()
    payload = json.loads(
        (first_dir / MANIFEST_ARTIFACT_NAME).read_text(encoding="utf-8")
    )
    assert payload["content_hash"].startswith("sha256:")
    assert payload["quality_hash"].startswith("sha256:")
    assert payload["manifest_hash"].startswith("sha256:")
    assert payload["row_count"] == 1
    assert payload["artifacts"][0]["path"] == DAILY_BARS_ARTIFACT_NAME
    assert "DATABASE_URL" not in json.dumps(payload)
    quality = json.loads(
        (first_dir / QUALITY_ARTIFACT_NAME).read_text(encoding="utf-8")
    )
    assert quality["corporate_actions"][0]["action_type"] == "split"
    assert first.manifest.content_hash == second.manifest.content_hash
    assert first.manifest.quality_hash == second.manifest.quality_hash
    after = set(list_public_tables(postgres_engine))
    assert after == before
    assert after <= _RESEARCH_TABLES


def test_pit_correction_changes_content_hash(
    db_session: Session, tmp_path: Path
) -> None:
    source = upsert_data_source(db_session, name=_unique("src"), vendor="local_csv")
    instrument = upsert_instrument(
        db_session, symbol=_unique("CORR"), asset_class="equity"
    )
    run = create_ingestion_run(db_session, source_id=source.id)
    _insert_bar(
        db_session,
        instrument=instrument,
        source_id=source.id,
        ingestion_run_id=run.id,
        day=1,
        available_day=2,
        close="10",
    )
    request = build_dataset_snapshot_request(
        as_of=datetime(2024, 1, 10, tzinfo=UTC),
        start_time=datetime(2024, 1, 1, tzinfo=UTC),
        end_time=datetime(2024, 1, 5, tzinfo=UTC),
        symbols=[instrument.symbol],
    )
    before = create_daily_bars_snapshot(
        db_session,
        request,
        tmp_path / "before",
        created_at=datetime(2024, 1, 10, tzinfo=UTC),
        resolve_git=False,
    )
    original = get_daily_bars(db_session, instrument_id=instrument.id)[0]
    insert_daily_bar_correction(
        db_session,
        superseded=original,
        available_time=datetime(2024, 1, 8, tzinfo=UTC),
        open=Decimal("10"),
        high=Decimal("12"),
        low=Decimal("9"),
        close=Decimal("11"),
        volume=Decimal("100"),
        ingestion_run_id=run.id,
        reason="restated close",
    )
    after = create_daily_bars_snapshot(
        db_session,
        request,
        tmp_path / "after",
        created_at=datetime(2024, 1, 10, tzinfo=UTC),
        resolve_git=False,
    )
    assert before.manifest.content_hash != after.manifest.content_hash
    assert after.manifest.row_count == 1
