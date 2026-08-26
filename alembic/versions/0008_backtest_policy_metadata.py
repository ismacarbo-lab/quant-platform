"""Backtest policy metadata columns.

Revision ID: 0008_backtest_policy_metadata
Revises: 0007_backtest_runs
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0008_backtest_policy_metadata"
down_revision: str | None = "0007_backtest_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "backtest_runs",
        sa.Column(
            "policy_config",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "backtest_runs",
        sa.Column("policy_output_hash", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_backtest_runs_policy_output_hash",
        "backtest_runs",
        ["policy_output_hash"],
    )


def downgrade() -> None:
    op.drop_index("ix_backtest_runs_policy_output_hash", table_name="backtest_runs")
    op.drop_column("backtest_runs", "policy_output_hash")
    op.drop_column("backtest_runs", "policy_config")
