"""Strategy backtest results (ADR 0005 paper-trading pivot).

Revision ID: 0011_strategy_backtests
Revises: 0010_normalized_dataset_catalog
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0011_strategy_backtests"
down_revision: str | None = "0010_normalized_dataset_catalog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "strategy_backtests",
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("strategy_name", sa.String(length=64), nullable=False),
        sa.Column("strategy_title", sa.String(length=128), nullable=False),
        sa.Column("params", JSONB(), nullable=False),
        sa.Column("benchmark_name", sa.String(length=64), nullable=False),
        sa.Column("source_name", sa.String(length=64), nullable=False),
        sa.Column("symbols", JSONB(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rebalance", sa.String(length=16), nullable=False),
        sa.Column("commission_bps", sa.Numeric(10, 4), nullable=False),
        sa.Column("slippage_bps", sa.Numeric(10, 4), nullable=False),
        sa.Column("initial_cash", sa.Numeric(20, 4), nullable=False),
        sa.Column("session_count", sa.Integer(), nullable=False),
        sa.Column("rebalance_count", sa.Integer(), nullable=False),
        sa.Column("metrics", JSONB(), nullable=False),
        sa.Column("benchmark_metrics", JSONB(), nullable=False),
        sa.Column("relative_metrics", JSONB(), nullable=False),
        sa.Column("walk_forward", JSONB(), nullable=True),
        sa.Column("promotion", JSONB(), nullable=True),
        sa.Column("promotion_eligible", sa.Boolean(), nullable=True),
        sa.Column("equity_curve", JSONB(), nullable=False),
        sa.Column("monthly_returns", JSONB(), nullable=False),
        sa.Column("latest_weights", JSONB(), nullable=False),
        sa.Column("data_hash", sa.Text(), nullable=False),
        sa.Column("result_hash", sa.Text(), nullable=False),
        sa.Column("package_version", sa.String(length=32), nullable=False),
        sa.Column("git_commit", sa.String(length=64), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "initial_cash > 0", name="ck_strategy_backtests_initial_cash"
        ),
        sa.CheckConstraint(
            "commission_bps >= 0 AND slippage_bps >= 0",
            name="ck_strategy_backtests_costs",
        ),
        sa.CheckConstraint("session_count >= 0", name="ck_strategy_backtests_sessions"),
        sa.PrimaryKeyConstraint("id", name="pk_strategy_backtests"),
    )
    op.create_index(
        "ix_strategy_backtests_strategy_created",
        "strategy_backtests",
        ["strategy_name", "created_at"],
    )
    op.create_index(
        "ix_strategy_backtests_created_at", "strategy_backtests", ["created_at"]
    )
    op.create_index(
        "ix_strategy_backtests_result_hash", "strategy_backtests", ["result_hash"]
    )


def downgrade() -> None:
    op.drop_index("ix_strategy_backtests_result_hash", table_name="strategy_backtests")
    op.drop_index("ix_strategy_backtests_created_at", table_name="strategy_backtests")
    op.drop_index(
        "ix_strategy_backtests_strategy_created", table_name="strategy_backtests"
    )
    op.drop_table("strategy_backtests")
