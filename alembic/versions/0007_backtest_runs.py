"""Backtest run catalog table (metadata only).

Revision ID: 0007_backtest_runs
Revises: 0006_replay_runs
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0007_backtest_runs"
down_revision: str | None = "0006_replay_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "backtest_runs",
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("backtest_id", sa.String(length=64), nullable=False),
        sa.Column("replay_id", sa.String(length=64), nullable=False),
        sa.Column("stream_hash", sa.Text(), nullable=False),
        sa.Column("backtest_hash", sa.Text(), nullable=False),
        sa.Column("manifest_hash", sa.Text(), nullable=False),
        sa.Column("policy_name", sa.String(length=64), nullable=False),
        sa.Column("package_version", sa.String(length=32), nullable=False),
        sa.Column("git_commit", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.Column("market_event_count", sa.Integer(), nullable=False),
        sa.Column("session_event_count", sa.Integer(), nullable=False),
        sa.Column("corporate_action_event_count", sa.Integer(), nullable=False),
        sa.Column("warning_count", sa.Integer(), nullable=False),
        sa.Column("error_count", sa.Integer(), nullable=False),
        sa.Column("is_reproducible", sa.Boolean(), nullable=False),
        sa.Column("is_usable", sa.Boolean(), nullable=False),
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
        sa.CheckConstraint("event_count >= 0", name="ck_backtest_runs_event_count"),
        sa.CheckConstraint(
            "market_event_count >= 0",
            name="ck_backtest_runs_market_event_count",
        ),
        sa.CheckConstraint(
            "session_event_count >= 0",
            name="ck_backtest_runs_session_event_count",
        ),
        sa.CheckConstraint(
            "corporate_action_event_count >= 0",
            name="ck_backtest_runs_ca_event_count",
        ),
        sa.CheckConstraint("warning_count >= 0", name="ck_backtest_runs_warning_count"),
        sa.CheckConstraint("error_count >= 0", name="ck_backtest_runs_error_count"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("backtest_id", name="uq_backtest_runs_backtest_id"),
        sa.UniqueConstraint("manifest_hash", name="uq_backtest_runs_manifest_hash"),
    )
    op.create_index("ix_backtest_runs_replay_id", "backtest_runs", ["replay_id"])
    op.create_index("ix_backtest_runs_stream_hash", "backtest_runs", ["stream_hash"])
    op.create_index(
        "ix_backtest_runs_backtest_hash", "backtest_runs", ["backtest_hash"]
    )
    op.create_index("ix_backtest_runs_policy_name", "backtest_runs", ["policy_name"])
    op.create_index("ix_backtest_runs_created_at", "backtest_runs", ["created_at"])
    op.create_index("ix_backtest_runs_is_usable", "backtest_runs", ["is_usable"])


def downgrade() -> None:
    op.drop_index("ix_backtest_runs_is_usable", table_name="backtest_runs")
    op.drop_index("ix_backtest_runs_created_at", table_name="backtest_runs")
    op.drop_index("ix_backtest_runs_policy_name", table_name="backtest_runs")
    op.drop_index("ix_backtest_runs_backtest_hash", table_name="backtest_runs")
    op.drop_index("ix_backtest_runs_stream_hash", table_name="backtest_runs")
    op.drop_index("ix_backtest_runs_replay_id", table_name="backtest_runs")
    op.drop_table("backtest_runs")
