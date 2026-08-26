"""Backtest experiment catalog table (metadata only).

Revision ID: 0009_backtest_experiments
Revises: 0008_backtest_policy_metadata
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0009_backtest_experiments"
down_revision: str | None = "0008_backtest_policy_metadata"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "backtest_experiments",
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("experiment_id", sa.String(length=64), nullable=False),
        sa.Column("experiment_name", sa.String(length=256), nullable=False),
        sa.Column("experiment_hash", sa.Text(), nullable=False),
        sa.Column("manifest_hash", sa.Text(), nullable=False),
        sa.Column("policy_name", sa.String(length=64), nullable=False),
        sa.Column("package_version", sa.String(length=32), nullable=False),
        sa.Column("git_commit", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("member_count", sa.Integer(), nullable=False),
        sa.Column("usable_count", sa.Integer(), nullable=False),
        sa.Column("error_count", sa.Integer(), nullable=False),
        sa.Column("warning_count", sa.Integer(), nullable=False),
        sa.Column("request", JSONB(), nullable=False),
        sa.Column("summary", JSONB(), nullable=False),
        sa.Column("artifacts", JSONB(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "registered_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "member_count >= 0", name="ck_backtest_experiments_member_count"
        ),
        sa.CheckConstraint(
            "usable_count >= 0", name="ck_backtest_experiments_usable_count"
        ),
        sa.CheckConstraint(
            "error_count >= 0", name="ck_backtest_experiments_error_count"
        ),
        sa.CheckConstraint(
            "warning_count >= 0", name="ck_backtest_experiments_warning_count"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "experiment_id", name="uq_backtest_experiments_experiment_id"
        ),
        sa.UniqueConstraint(
            "manifest_hash", name="uq_backtest_experiments_manifest_hash"
        ),
    )
    op.create_index(
        "ix_backtest_experiments_experiment_hash",
        "backtest_experiments",
        ["experiment_hash"],
    )
    op.create_index(
        "ix_backtest_experiments_experiment_name",
        "backtest_experiments",
        ["experiment_name"],
    )
    op.create_index(
        "ix_backtest_experiments_policy_name",
        "backtest_experiments",
        ["policy_name"],
    )
    op.create_index(
        "ix_backtest_experiments_created_at",
        "backtest_experiments",
        ["created_at"],
    )
    op.create_index(
        "ix_backtest_experiments_error_count",
        "backtest_experiments",
        ["error_count"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_backtest_experiments_error_count", table_name="backtest_experiments"
    )
    op.drop_index(
        "ix_backtest_experiments_created_at", table_name="backtest_experiments"
    )
    op.drop_index(
        "ix_backtest_experiments_policy_name", table_name="backtest_experiments"
    )
    op.drop_index(
        "ix_backtest_experiments_experiment_name", table_name="backtest_experiments"
    )
    op.drop_index(
        "ix_backtest_experiments_experiment_hash", table_name="backtest_experiments"
    )
    op.drop_table("backtest_experiments")
