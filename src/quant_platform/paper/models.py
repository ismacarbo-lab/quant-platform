"""Paper-trading persistence (fictional money). Not a real broker ledger."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
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
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from quant_platform.core.time import utc_now
from quant_platform.storage.database import Base

ACCOUNT_STATUSES: tuple[str, ...] = ("active", "paused")
ORDER_SIDES: tuple[str, ...] = ("buy", "sell")
ORDER_STATUSES: tuple[str, ...] = ("pending", "filled", "rejected", "cancelled")
RUN_STATUSES: tuple[str, ...] = ("ok", "skipped", "error")


class PaperAccount(Base):
    __tablename__ = "paper_accounts"
    __table_args__ = (
        UniqueConstraint("name", name="uq_paper_accounts_name"),
        CheckConstraint("initial_cash > 0", name="ck_paper_accounts_initial_cash"),
        CheckConstraint(
            "status IN ('active', 'paused')", name="ck_paper_accounts_status"
        ),
        CheckConstraint(
            "commission_bps >= 0 AND slippage_bps >= 0",
            name="ck_paper_accounts_costs",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_name: Mapped[str] = mapped_column(String(64), nullable=False)
    params: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    initial_cash: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    cash: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    rebalance: Mapped[str] = mapped_column(String(16), nullable=False)
    commission_bps: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    slippage_bps: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    benchmark_symbol: Mapped[str] = mapped_column(
        String(16), nullable=False, default="SPY"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    started_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_run_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_equity: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class PaperRun(Base):
    """One daily engine run for one account. Unique per session date."""

    __tablename__ = "paper_runs"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "session_date", name="uq_paper_runs_account_session"
        ),
        CheckConstraint(
            "status IN ('ok', 'skipped', 'error')", name="ck_paper_runs_status"
        ),
        Index("ix_paper_runs_account_session", "account_id", "session_date"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("paper_accounts.id"), nullable=False
    )
    session_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    replayed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rebalanced: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    orders_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fills_executed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dividends_credited: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False, default=Decimal("0")
    )
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class PaperOrder(Base):
    __tablename__ = "paper_orders"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "session_date",
            "symbol",
            name="uq_paper_orders_account_session_symbol",
        ),
        CheckConstraint("side IN ('buy', 'sell')", name="ck_paper_orders_side"),
        CheckConstraint("quantity > 0", name="ck_paper_orders_quantity"),
        CheckConstraint(
            "status IN ('pending', 'filled', 'rejected', 'cancelled')",
            name="ck_paper_orders_status",
        ),
        Index("ix_paper_orders_account_status", "account_id", "status"),
        Index("ix_paper_orders_account_session", "account_id", "session_date"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("paper_accounts.id"), nullable=False
    )
    session_date: Mapped[date] = mapped_column(Date, nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(28, 8), nullable=False)
    order_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="market"
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    target_weight: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    reference_price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class PaperFill(Base):
    __tablename__ = "paper_fills"
    __table_args__ = (
        UniqueConstraint("order_id", name="uq_paper_fills_order"),
        CheckConstraint("quantity > 0", name="ck_paper_fills_quantity"),
        CheckConstraint("price > 0", name="ck_paper_fills_price"),
        Index("ix_paper_fills_account_date", "account_id", "fill_date"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    order_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("paper_orders.id"), nullable=False
    )
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("paper_accounts.id"), nullable=False
    )
    fill_date: Mapped[date] = mapped_column(Date, nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(28, 8), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    reference_price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    commission: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    slippage_cost: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    broker: Mapped[str] = mapped_column(String(32), nullable=False, default="simulated")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class PaperPosition(Base):
    __tablename__ = "paper_positions"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "symbol", name="uq_paper_positions_account_symbol"
        ),
        CheckConstraint("quantity >= 0", name="ck_paper_positions_long_only"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("paper_accounts.id"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(28, 8), nullable=False)
    average_cost: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class PaperEquitySnapshot(Base):
    __tablename__ = "paper_equity_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "session_date", name="uq_paper_equity_account_session"
        ),
        Index("ix_paper_equity_account_session", "account_id", "session_date"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("paper_accounts.id"), nullable=False
    )
    session_date: Mapped[date] = mapped_column(Date, nullable=False)
    cash: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    positions_value: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    equity: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    daily_return: Mapped[Decimal | None] = mapped_column(Numeric(12, 8), nullable=True)
    benchmark_equity: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 4), nullable=True
    )
    weights: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    replayed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
