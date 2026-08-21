"""SQLAlchemy models for local research ingestion.

These tables store point-in-time daily OHLCV from local CSV. They are not
broker, order, or execution models. The JSON payload column is named
``run_metadata`` because SQLAlchemy reserves ``metadata`` on declarative
classes.

Instrument uniqueness uses PostgreSQL ``UNIQUE NULLS NOT DISTINCT`` so
NULL exchange/currency compare equal in the natural key.
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from quant_platform.core.time import utc_now
from quant_platform.storage.database import Base


class IngestionStatus(StrEnum):
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class DataSource(Base):
    __tablename__ = "data_sources"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    vendor: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class MarketCalendar(Base):
    """Manual research calendar. Not downloaded from an exchange."""

    __tablename__ = "market_calendars"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class MarketSession(Base):
    """One civil date in a manual calendar (open, holiday, or closed)."""

    __tablename__ = "market_sessions"
    __table_args__ = (
        UniqueConstraint(
            "calendar_id", "session_date", name="uq_market_sessions_calendar_date"
        ),
        Index("ix_market_sessions_calendar_date", "calendar_id", "session_date"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    calendar_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("market_calendars.id"), nullable=False
    )
    session_date: Mapped[date] = mapped_column(Date, nullable=False)
    open_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    close_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    is_open: Mapped[bool] = mapped_column(Boolean, nullable=False)
    note: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class Instrument(Base):
    __tablename__ = "instruments"
    __table_args__ = (
        UniqueConstraint(
            "symbol",
            "asset_class",
            "exchange",
            "currency",
            name="uq_instruments_natural_key",
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_instruments_symbol", "symbol"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    asset_class: Mapped[str] = mapped_column(String(32), nullable=False)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    exchange: Mapped[str | None] = mapped_column(String(32), nullable=True)
    calendar_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("market_calendars.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class InstrumentIdentifier(Base):
    """Local alternate identifier. Namespaces are placeholders, not vendors."""

    __tablename__ = "instrument_identifiers"
    __table_args__ = (
        UniqueConstraint(
            "namespace",
            "value",
            "valid_from",
            name="uq_instrument_identifiers_ns_value_from",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to > valid_from",
            name="ck_instrument_identifiers_valid_range",
        ),
        Index("ix_instrument_identifiers_instrument", "instrument_id"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    instrument_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("instruments.id"), nullable=False
    )
    namespace: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[str] = mapped_column(String(128), nullable=False)
    valid_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    valid_to: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"
    __table_args__ = (
        Index("ix_ingestion_runs_source_started", "source_id", "started_at"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    source_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("data_sources.id"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    accepted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    run_metadata: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)


class DailyBar(Base):
    __tablename__ = "daily_bars"
    __table_args__ = (
        UniqueConstraint(
            "instrument_id",
            "source_id",
            "observation_time",
            "available_time",
            name="uq_daily_bars_pit",
        ),
        CheckConstraint("high >= low", name="ck_daily_bars_high_gte_low"),
        CheckConstraint(
            "open >= 0 AND high >= 0 AND low >= 0 AND close >= 0",
            name="ck_daily_bars_prices_non_negative",
        ),
        CheckConstraint(
            "volume IS NULL OR volume >= 0",
            name="ck_daily_bars_volume_non_negative",
        ),
        CheckConstraint(
            "available_time > observation_time",
            name="ck_daily_bars_available_after_observation",
        ),
        CheckConstraint(
            "supersedes_daily_bar_id IS NULL OR is_correction = true",
            name="ck_daily_bars_supersedes_is_correction",
        ),
        Index(
            "ix_daily_bars_instrument_observation", "instrument_id", "observation_time"
        ),
        Index("ix_daily_bars_instrument_available", "instrument_id", "available_time"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    instrument_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("instruments.id"), nullable=False
    )
    source_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("data_sources.id"), nullable=False
    )
    observation_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    available_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    open: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    volume: Mapped[Decimal | None] = mapped_column(Numeric(28, 8), nullable=True)
    ingestion_run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("ingestion_runs.id"), nullable=False
    )
    is_correction: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    correction_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    supersedes_daily_bar_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("daily_bars.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class RawIngestionRecord(Base):
    """Bronze row: the payload as received, before silver validation."""

    __tablename__ = "raw_ingestion_records"
    __table_args__ = (
        UniqueConstraint(
            "ingestion_run_id",
            "record_index",
            name="uq_raw_ingestion_run_index",
        ),
        CheckConstraint("record_index >= 0", name="ck_raw_ingestion_record_index"),
        Index("ix_raw_ingestion_source_hash", "source_id", "payload_hash"),
        Index("ix_raw_ingestion_run_index", "ingestion_run_id", "record_index"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    ingestion_run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("ingestion_runs.id"), nullable=False
    )
    source_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("data_sources.id"), nullable=False
    )
    record_index: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class IngestionError(Base):
    """Bronze quality record for a rejected row or file-level failure."""

    __tablename__ = "ingestion_errors"
    __table_args__ = (Index("ix_ingestion_errors_run", "ingestion_run_id"),)

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    ingestion_run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("ingestion_runs.id"), nullable=False
    )
    source_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("data_sources.id"), nullable=False
    )
    record_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str] = mapped_column(String(64), nullable=False)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    raw_payload: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
