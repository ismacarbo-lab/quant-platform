"""SQLAlchemy models for local research ingestion.

These tables store point-in-time daily OHLCV from local CSV. They are not
broker, order, or execution models. The JSON payload column is named
``run_metadata`` because SQLAlchemy reserves ``metadata`` on declarative
classes.

Instrument uniqueness uses PostgreSQL ``UNIQUE NULLS NOT DISTINCT`` on
``(symbol, asset_class, exchange_id, currency)`` so NULL exchange or
currency compare equal in the natural key.
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


class IdentifierNamespace(StrEnum):
    ISIN = "isin"
    FIGI = "figi"
    CUSIP = "cusip"
    LOCAL_SYMBOL = "local_symbol"
    VENDOR_SYMBOL = "vendor_symbol"


class SessionKind(StrEnum):
    OPEN = "open"
    HOLIDAY = "holiday"
    HALF_SESSION = "half_session"
    EXCEPTIONAL_CLOSE = "exceptional_close"


class CorporateActionType(StrEnum):
    SPLIT = "split"
    REVERSE_SPLIT = "reverse_split"
    DIVIDEND = "dividend"
    SYMBOL_CHANGE = "symbol_change"
    DELISTING = "delisting"


OPEN_SESSION_KINDS = frozenset({SessionKind.OPEN, SessionKind.HALF_SESSION})
ALLOWED_IDENTIFIER_NAMESPACES = frozenset(item.value for item in IdentifierNamespace)
ALLOWED_SESSION_KINDS = frozenset(item.value for item in SessionKind)
ALLOWED_CORPORATE_ACTION_TYPES = frozenset(item.value for item in CorporateActionType)


def session_kind_is_open(kind: str) -> bool:
    return kind in {item.value for item in OPEN_SESSION_KINDS}


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


class Exchange(Base):
    """Research venue. Not a broker adapter."""

    __tablename__ = "exchanges"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    mic: Mapped[str | None] = mapped_column(String(8), nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    country: Mapped[str | None] = mapped_column(String(8), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
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
        CheckConstraint(
            "session_kind IN ('open', 'holiday', 'half_session', 'exceptional_close')",
            name="ck_market_sessions_kind",
        ),
        CheckConstraint(
            "("
            "session_kind IN ('open', 'half_session') AND is_open = true"
            ") OR ("
            "session_kind IN ('holiday', 'exceptional_close') AND is_open = false"
            ")",
            name="ck_market_sessions_kind_open",
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
    session_kind: Mapped[str] = mapped_column(String(32), nullable=False)
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
            "exchange_id",
            "currency",
            name="uq_instruments_natural_key",
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_instruments_symbol", "symbol"),
        Index("ix_instruments_exchange", "exchange_id"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    asset_class: Mapped[str] = mapped_column(String(32), nullable=False)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    exchange_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("exchanges.id"), nullable=True
    )
    calendar_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("market_calendars.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class InstrumentIdentifier(Base):
    """Local alternate identifier. Namespaces are stored strings, not vendors."""

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
        CheckConstraint(
            "namespace IN ('isin', 'figi', 'cusip', 'local_symbol', 'vendor_symbol')",
            name="ck_instrument_identifiers_namespace",
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
        CheckConstraint(
            "superseded_by_daily_bar_id IS NULL OR superseded_by_daily_bar_id <> id",
            name="ck_daily_bars_superseded_by_not_self",
        ),
        CheckConstraint(
            "supersedes_daily_bar_id IS NULL OR supersedes_daily_bar_id <> id",
            name="ck_daily_bars_supersedes_not_self",
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
    superseded_by_daily_bar_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("daily_bars.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class CorporateAction(Base):
    """Stored corporate event. Adjustments are not applied in this phase."""

    __tablename__ = "corporate_actions"
    __table_args__ = (
        CheckConstraint(
            "action_type IN ('split', 'reverse_split', 'dividend', "
            "'symbol_change', 'delisting')",
            name="ck_corporate_actions_type",
        ),
        Index(
            "ix_corporate_actions_instrument_effective",
            "instrument_id",
            "effective_time",
        ),
        Index(
            "ix_corporate_actions_instrument_available",
            "instrument_id",
            "available_time",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    instrument_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("instruments.id"), nullable=False
    )
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    effective_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    available_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    quantity_before: Mapped[Decimal | None] = mapped_column(
        Numeric(28, 8), nullable=True
    )
    quantity_after: Mapped[Decimal | None] = mapped_column(
        Numeric(28, 8), nullable=True
    )
    cash_amount: Mapped[Decimal | None] = mapped_column(Numeric(28, 8), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    old_value: Mapped[str | None] = mapped_column(String(64), nullable=True)
    new_value: Mapped[str | None] = mapped_column(String(64), nullable=True)
    note: Mapped[str | None] = mapped_column(String(256), nullable=True)
    details: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
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


class DatasetSnapshotRecord(Base):
    """Catalog metadata for a local research snapshot. Does not store OHLCV rows."""

    __tablename__ = "dataset_snapshots"
    __table_args__ = (
        UniqueConstraint("snapshot_id", name="uq_dataset_snapshots_snapshot_id"),
        UniqueConstraint("manifest_hash", name="uq_dataset_snapshots_manifest_hash"),
        CheckConstraint("row_count >= 0", name="ck_dataset_snapshots_row_count"),
        CheckConstraint(
            "instrument_count >= 0", name="ck_dataset_snapshots_instrument_count"
        ),
        CheckConstraint(
            "warning_count >= 0", name="ck_dataset_snapshots_warning_count"
        ),
        CheckConstraint("error_count >= 0", name="ck_dataset_snapshots_error_count"),
        Index("ix_dataset_snapshots_content_hash", "content_hash"),
        Index("ix_dataset_snapshots_as_of", "as_of"),
        Index("ix_dataset_snapshots_window", "start_time", "end_time"),
        Index("ix_dataset_snapshots_git_commit", "git_commit"),
        Index("ix_dataset_snapshots_is_usable", "is_usable"),
        Index("ix_dataset_snapshots_error_count", "error_count"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    snapshot_id: Mapped[str] = mapped_column(String(64), nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    quality_hash: Mapped[str] = mapped_column(Text, nullable=False)
    manifest_hash: Mapped[str] = mapped_column(Text, nullable=False)
    package_version: Mapped[str] = mapped_column(String(32), nullable=False)
    git_commit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    instrument_count: Mapped[int] = mapped_column(Integer, nullable=False)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False)
    is_reproducible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_usable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    dataset_request: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    quality_summary: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    artifacts: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class SimulationReplayRunRecord(Base):
    """Catalog metadata for a local replay run. Does not store event rows."""

    __tablename__ = "simulation_replay_runs"
    __table_args__ = (
        UniqueConstraint("replay_id", name="uq_simulation_replay_runs_replay_id"),
        UniqueConstraint(
            "manifest_hash", name="uq_simulation_replay_runs_manifest_hash"
        ),
        CheckConstraint(
            "event_count >= 0", name="ck_simulation_replay_runs_event_count"
        ),
        CheckConstraint(
            "market_event_count >= 0",
            name="ck_simulation_replay_runs_market_event_count",
        ),
        CheckConstraint(
            "session_event_count >= 0",
            name="ck_simulation_replay_runs_session_event_count",
        ),
        CheckConstraint(
            "corporate_action_event_count >= 0",
            name="ck_simulation_replay_runs_ca_event_count",
        ),
        CheckConstraint(
            "pre_known_event_count >= 0",
            name="ck_simulation_replay_runs_pre_known_event_count",
        ),
        CheckConstraint(
            "warning_count >= 0", name="ck_simulation_replay_runs_warning_count"
        ),
        CheckConstraint(
            "error_count >= 0", name="ck_simulation_replay_runs_error_count"
        ),
        CheckConstraint(
            "source_type IN ('database', 'snapshot')",
            name="ck_simulation_replay_runs_source_type",
        ),
        Index("ix_simulation_replay_runs_stream_hash", "stream_hash"),
        Index("ix_simulation_replay_runs_source_type", "source_type"),
        Index("ix_simulation_replay_runs_dataset_snapshot_id", "dataset_snapshot_id"),
        Index("ix_simulation_replay_runs_created_at", "created_at"),
        Index("ix_simulation_replay_runs_is_usable", "is_usable"),
        Index("ix_simulation_replay_runs_boundary_ok", "boundary_ok"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    replay_id: Mapped[str] = mapped_column(String(64), nullable=False)
    stream_hash: Mapped[str] = mapped_column(Text, nullable=False)
    manifest_hash: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    dataset_snapshot_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dataset_content_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    package_version: Mapped[str] = mapped_column(String(32), nullable=False)
    git_commit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    as_of: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    start_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    end_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    market_event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    session_event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    corporate_action_event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    pre_known_event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False)
    boundary_ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_reproducible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_usable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    request: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    audit_summary: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    artifacts: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class BacktestRunRecord(Base):
    """Catalog metadata for a local dry-run backtest. No orders or PnL."""

    __tablename__ = "backtest_runs"
    __table_args__ = (
        UniqueConstraint("backtest_id", name="uq_backtest_runs_backtest_id"),
        UniqueConstraint("manifest_hash", name="uq_backtest_runs_manifest_hash"),
        CheckConstraint("event_count >= 0", name="ck_backtest_runs_event_count"),
        CheckConstraint(
            "market_event_count >= 0",
            name="ck_backtest_runs_market_event_count",
        ),
        CheckConstraint(
            "session_event_count >= 0",
            name="ck_backtest_runs_session_event_count",
        ),
        CheckConstraint(
            "corporate_action_event_count >= 0",
            name="ck_backtest_runs_ca_event_count",
        ),
        CheckConstraint("warning_count >= 0", name="ck_backtest_runs_warning_count"),
        CheckConstraint("error_count >= 0", name="ck_backtest_runs_error_count"),
        Index("ix_backtest_runs_replay_id", "replay_id"),
        Index("ix_backtest_runs_stream_hash", "stream_hash"),
        Index("ix_backtest_runs_backtest_hash", "backtest_hash"),
        Index("ix_backtest_runs_policy_name", "policy_name"),
        Index("ix_backtest_runs_policy_output_hash", "policy_output_hash"),
        Index("ix_backtest_runs_created_at", "created_at"),
        Index("ix_backtest_runs_is_usable", "is_usable"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    backtest_id: Mapped[str] = mapped_column(String(64), nullable=False)
    replay_id: Mapped[str] = mapped_column(String(64), nullable=False)
    stream_hash: Mapped[str] = mapped_column(Text, nullable=False)
    backtest_hash: Mapped[str] = mapped_column(Text, nullable=False)
    manifest_hash: Mapped[str] = mapped_column(Text, nullable=False)
    policy_name: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_config: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    policy_output_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    package_version: Mapped[str] = mapped_column(String(32), nullable=False)
    git_commit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    market_event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    session_event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    corporate_action_event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False)
    is_reproducible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_usable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    request: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    summary: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    artifacts: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
