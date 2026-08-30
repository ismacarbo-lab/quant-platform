"""PostgreSQL tests for derived corporate-action normalization. No trading."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from quant_platform.core.config import Settings
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
    hash_normalized_daily_bars_dataset,
    verify_normalization_artifacts,
    write_normalized_dataset_artifacts,
)
from quant_platform.simulation.constructs import detect_trading_constructs

pytestmark = pytest.mark.postgres


def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:8]}"


def _draft(
    symbol: str,
    *,
    day: int,
    available_day: int,
    close: str,
) -> DailyBarDraft:
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
    quantity_after: str = "4",
    action_type: str = "split",
    available_day: int = 1,
    effective_day: int = 10,
    cash_amount: Decimal | None = None,
) -> tuple[object, object, object]:
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
    action = create_corporate_action(
        session,
        instrument_id=instrument.id,
        action_type=action_type,
        effective_time=datetime(2024, 1, effective_day, tzinfo=UTC),
        available_time=datetime(2024, 1, available_day, 20, tzinfo=UTC),
        quantity_before=None if cash_amount is not None else Decimal("1"),
        quantity_after=None if cash_amount is not None else Decimal(quantity_after),
        cash_amount=cash_amount,
    )
    return source, instrument, action


def test_normalized_dataset_applies_visible_split(db_session: Session) -> None:
    symbol = _unique("NSPL")
    source_name = _unique("src")
    _source, instrument, action = _seed_split(
        db_session, symbol=symbol, source_name=source_name
    )
    request = build_normalization_request(
        as_of=datetime(2024, 1, 20, tzinfo=UTC),
        start_time=datetime(2024, 1, 1, tzinfo=UTC),
        end_time=datetime(2024, 1, 5, tzinfo=UTC),
        source_name=source_name,
        symbols=[symbol],
        adjustment_mode=AdjustmentMode.SPLIT_ONLY,
    )
    dataset = build_normalized_daily_bars_dataset(db_session, request)
    assert len(dataset.rows) == 1
    row = dataset.rows[0]
    assert row.raw_close == Decimal("40")
    assert row.normalized_close == Decimal("10")
    assert row.normalized_volume == Decimal("400")
    assert row.applied_action_ids == (str(action.id),)
    stored = get_daily_bars(db_session, instrument_id=instrument.id)
    assert [item.close for item in stored] == [Decimal("40")]


def test_future_split_not_visible_by_as_of(db_session: Session) -> None:
    symbol = _unique("NFUT")
    source_name = _unique("src")
    _seed_split(
        db_session,
        symbol=symbol,
        source_name=source_name,
        available_day=25,
    )
    request = build_normalization_request(
        as_of=datetime(2024, 1, 20, tzinfo=UTC),
        start_time=datetime(2024, 1, 1, tzinfo=UTC),
        end_time=datetime(2024, 1, 5, tzinfo=UTC),
        source_name=source_name,
        symbols=[symbol],
    )
    dataset = build_normalized_daily_bars_dataset(db_session, request)
    assert dataset.rows[0].normalized_close == Decimal("40")
    assert dataset.rows[0].applied_action_ids == ()


def test_dividend_warns_and_does_not_adjust(db_session: Session) -> None:
    symbol = _unique("NDIV")
    source_name = _unique("src")
    _seed_split(
        db_session,
        symbol=symbol,
        source_name=source_name,
        action_type="dividend",
        cash_amount=Decimal("0.25"),
    )
    request = build_normalization_request(
        as_of=datetime(2024, 1, 20, tzinfo=UTC),
        start_time=datetime(2024, 1, 1, tzinfo=UTC),
        end_time=datetime(2024, 1, 5, tzinfo=UTC),
        source_name=source_name,
        symbols=[symbol],
    )
    dataset = build_normalized_daily_bars_dataset(db_session, request)
    assert dataset.rows[0].normalized_close == Decimal("40")
    assert [item.code for item in dataset.report.issues] == ["dividend_not_adjusted"]


def test_raw_daily_bars_table_is_unchanged(db_session: Session) -> None:
    symbol = _unique("NRAW")
    source_name = _unique("src")
    _source, instrument, _action = _seed_split(
        db_session, symbol=symbol, source_name=source_name
    )
    before = [
        (row.id, row.close, row.volume, row.available_time)
        for row in get_daily_bars(db_session, instrument_id=instrument.id)
    ]
    request = build_normalization_request(
        as_of=datetime(2024, 1, 20, tzinfo=UTC),
        start_time=datetime(2024, 1, 1, tzinfo=UTC),
        end_time=datetime(2024, 1, 5, tzinfo=UTC),
        source_name=source_name,
        symbols=[symbol],
    )
    build_normalized_daily_bars_dataset(db_session, request)
    after = [
        (row.id, row.close, row.volume, row.available_time)
        for row in get_daily_bars(db_session, instrument_id=instrument.id)
    ]
    assert after == before


def test_normalized_hash_stable_and_artifacts_verify(
    db_session: Session, tmp_path: Path
) -> None:
    symbol = _unique("NHSH")
    source_name = _unique("src")
    _seed_split(db_session, symbol=symbol, source_name=source_name)
    request = build_normalization_request(
        as_of=datetime(2024, 1, 20, tzinfo=UTC),
        start_time=datetime(2024, 1, 1, tzinfo=UTC),
        end_time=datetime(2024, 1, 5, tzinfo=UTC),
        source_name=source_name,
        symbols=[symbol],
    )
    first = build_normalized_daily_bars_dataset(db_session, request)
    second = build_normalized_daily_bars_dataset(db_session, request)
    assert first.dataset_hash == second.dataset_hash
    assert first.dataset_hash == hash_normalized_daily_bars_dataset(first)
    write_normalized_dataset_artifacts(first, tmp_path)
    report = verify_normalization_artifacts(tmp_path)
    assert report.ok is True


def test_no_trading_tables_or_packages(research_settings: Settings) -> None:
    findings = detect_trading_constructs()
    assert findings == ()
    assert research_settings.is_research_mode is True
    assert research_settings.app_mode.value == "research"
