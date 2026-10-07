"""Paper-trading tables with fictional cash (ADR 0005). No real broker.

Revision ID: 0012_paper_trading
Revises: 0011_strategy_backtests
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0012_paper_trading"
down_revision: str | None = "0011_strategy_backtests"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _uuid_pk() -> sa.Column:  # type: ignore[type-arg]
    return sa.Column(
        "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
    )


def _created_at() -> sa.Column:  # type: ignore[type-arg]
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "paper_accounts",
        _uuid_pk(),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("strategy_name", sa.String(length=64), nullable=False),
        sa.Column("params", JSONB(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("initial_cash", sa.Numeric(20, 4), nullable=False),
        sa.Column("cash", sa.Numeric(20, 4), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("rebalance", sa.String(length=16), nullable=False),
        sa.Column("commission_bps", sa.Numeric(10, 4), nullable=False),
        sa.Column("slippage_bps", sa.Numeric(10, 4), nullable=False),
        sa.Column("benchmark_symbol", sa.String(length=16), nullable=False),
        _created_at(),
        sa.Column("started_on", sa.Date(), nullable=True),
        sa.Column("last_run_date", sa.Date(), nullable=True),
        sa.Column("last_equity", sa.Numeric(20, 4), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.CheckConstraint("initial_cash > 0", name="ck_paper_accounts_initial_cash"),
        sa.CheckConstraint(
            "status IN ('active', 'paused')", name="ck_paper_accounts_status"
        ),
        sa.CheckConstraint(
            "commission_bps >= 0 AND slippage_bps >= 0",
            name="ck_paper_accounts_costs",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_paper_accounts"),
        sa.UniqueConstraint("name", name="uq_paper_accounts_name"),
    )
    op.create_table(
        "paper_runs",
        _uuid_pk(),
        sa.Column(
            "account_id",
            sa.Uuid(),
            sa.ForeignKey("paper_accounts.id", name="fk_paper_runs_account"),
            nullable=False,
        ),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("replayed", sa.Boolean(), nullable=False),
        sa.Column("rebalanced", sa.Boolean(), nullable=False),
        sa.Column("orders_created", sa.Integer(), nullable=False),
        sa.Column("fills_executed", sa.Integer(), nullable=False),
        sa.Column("dividends_credited", sa.Numeric(20, 4), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("data_hash", sa.Text(), nullable=True),
        _created_at(),
        sa.CheckConstraint(
            "status IN ('ok', 'skipped', 'error')", name="ck_paper_runs_status"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_paper_runs"),
        sa.UniqueConstraint(
            "account_id", "session_date", name="uq_paper_runs_account_session"
        ),
    )
    op.create_index(
        "ix_paper_runs_account_session", "paper_runs", ["account_id", "session_date"]
    )
    op.create_table(
        "paper_orders",
        _uuid_pk(),
        sa.Column(
            "account_id",
            sa.Uuid(),
            sa.ForeignKey("paper_accounts.id", name="fk_paper_orders_account"),
            nullable=False,
        ),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("side", sa.String(length=4), nullable=False),
        sa.Column("quantity", sa.Numeric(28, 8), nullable=False),
        sa.Column("order_type", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("target_weight", sa.Numeric(10, 6), nullable=False),
        sa.Column("reference_price", sa.Numeric(20, 8), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        _created_at(),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("side IN ('buy', 'sell')", name="ck_paper_orders_side"),
        sa.CheckConstraint("quantity > 0", name="ck_paper_orders_quantity"),
        sa.CheckConstraint(
            "status IN ('pending', 'filled', 'rejected', 'cancelled')",
            name="ck_paper_orders_status",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_paper_orders"),
        sa.UniqueConstraint(
            "account_id",
            "session_date",
            "symbol",
            name="uq_paper_orders_account_session_symbol",
        ),
    )
    op.create_index(
        "ix_paper_orders_account_status", "paper_orders", ["account_id", "status"]
    )
    op.create_index(
        "ix_paper_orders_account_session",
        "paper_orders",
        ["account_id", "session_date"],
    )
    op.create_table(
        "paper_fills",
        _uuid_pk(),
        sa.Column(
            "order_id",
            sa.Uuid(),
            sa.ForeignKey("paper_orders.id", name="fk_paper_fills_order"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            sa.Uuid(),
            sa.ForeignKey("paper_accounts.id", name="fk_paper_fills_account"),
            nullable=False,
        ),
        sa.Column("fill_date", sa.Date(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("side", sa.String(length=4), nullable=False),
        sa.Column("quantity", sa.Numeric(28, 8), nullable=False),
        sa.Column("price", sa.Numeric(20, 8), nullable=False),
        sa.Column("reference_price", sa.Numeric(20, 8), nullable=False),
        sa.Column("commission", sa.Numeric(20, 6), nullable=False),
        sa.Column("slippage_cost", sa.Numeric(20, 6), nullable=False),
        sa.Column("broker", sa.String(length=32), nullable=False),
        _created_at(),
        sa.CheckConstraint("quantity > 0", name="ck_paper_fills_quantity"),
        sa.CheckConstraint("price > 0", name="ck_paper_fills_price"),
        sa.PrimaryKeyConstraint("id", name="pk_paper_fills"),
        sa.UniqueConstraint("order_id", name="uq_paper_fills_order"),
    )
    op.create_index(
        "ix_paper_fills_account_date", "paper_fills", ["account_id", "fill_date"]
    )
    op.create_table(
        "paper_positions",
        _uuid_pk(),
        sa.Column(
            "account_id",
            sa.Uuid(),
            sa.ForeignKey("paper_accounts.id", name="fk_paper_positions_account"),
            nullable=False,
        ),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("quantity", sa.Numeric(28, 8), nullable=False),
        sa.Column("average_cost", sa.Numeric(20, 8), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("quantity >= 0", name="ck_paper_positions_long_only"),
        sa.PrimaryKeyConstraint("id", name="pk_paper_positions"),
        sa.UniqueConstraint(
            "account_id", "symbol", name="uq_paper_positions_account_symbol"
        ),
    )
    op.create_table(
        "paper_equity_snapshots",
        _uuid_pk(),
        sa.Column(
            "account_id",
            sa.Uuid(),
            sa.ForeignKey("paper_accounts.id", name="fk_paper_equity_account"),
            nullable=False,
        ),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("cash", sa.Numeric(20, 4), nullable=False),
        sa.Column("positions_value", sa.Numeric(20, 4), nullable=False),
        sa.Column("equity", sa.Numeric(20, 4), nullable=False),
        sa.Column("daily_return", sa.Numeric(12, 8), nullable=True),
        sa.Column("benchmark_equity", sa.Numeric(20, 4), nullable=True),
        sa.Column("weights", JSONB(), nullable=False),
        sa.Column("replayed", sa.Boolean(), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name="pk_paper_equity_snapshots"),
        sa.UniqueConstraint(
            "account_id", "session_date", name="uq_paper_equity_account_session"
        ),
    )
    op.create_index(
        "ix_paper_equity_account_session",
        "paper_equity_snapshots",
        ["account_id", "session_date"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_paper_equity_account_session", table_name="paper_equity_snapshots"
    )
    op.drop_table("paper_equity_snapshots")
    op.drop_table("paper_positions")
    op.drop_index("ix_paper_fills_account_date", table_name="paper_fills")
    op.drop_table("paper_fills")
    op.drop_index("ix_paper_orders_account_session", table_name="paper_orders")
    op.drop_index("ix_paper_orders_account_status", table_name="paper_orders")
    op.drop_table("paper_orders")
    op.drop_index("ix_paper_runs_account_session", table_name="paper_runs")
    op.drop_table("paper_runs")
    op.drop_table("paper_accounts")
