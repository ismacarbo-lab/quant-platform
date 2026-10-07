"""Persistence for strategy backtests (ADR 0005). Results, not orders."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from quant_platform.core.time import utc_now
from quant_platform.storage.database import Base


class StrategyBacktestRecord(Base):
    """One stored backtest: config, metrics, equity curve, promotion verdict."""

    __tablename__ = "strategy_backtests"
    __table_args__ = (
        CheckConstraint("initial_cash > 0", name="ck_strategy_backtests_initial_cash"),
        CheckConstraint(
            "commission_bps >= 0 AND slippage_bps >= 0",
            name="ck_strategy_backtests_costs",
        ),
        CheckConstraint("session_count >= 0", name="ck_strategy_backtests_sessions"),
        Index("ix_strategy_backtests_strategy_created", "strategy_name", "created_at"),
        Index("ix_strategy_backtests_created_at", "created_at"),
        Index("ix_strategy_backtests_result_hash", "result_hash"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    strategy_name: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_title: Mapped[str] = mapped_column(String(128), nullable=False)
    params: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    benchmark_name: Mapped[str] = mapped_column(String(64), nullable=False)
    source_name: Mapped[str] = mapped_column(String(64), nullable=False)
    symbols: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rebalance: Mapped[str] = mapped_column(String(16), nullable=False)
    commission_bps: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)
    slippage_bps: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)
    initial_cash: Mapped[float] = mapped_column(Numeric(20, 4), nullable=False)
    session_count: Mapped[int] = mapped_column(Integer, nullable=False)
    rebalance_count: Mapped[int] = mapped_column(Integer, nullable=False)
    metrics: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    benchmark_metrics: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    relative_metrics: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    walk_forward: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    promotion: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    promotion_eligible: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    equity_curve: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    monthly_returns: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False
    )
    latest_weights: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    data_hash: Mapped[str] = mapped_column(Text, nullable=False)
    result_hash: Mapped[str] = mapped_column(Text, nullable=False)
    package_version: Mapped[str] = mapped_column(String(32), nullable=False)
    git_commit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
