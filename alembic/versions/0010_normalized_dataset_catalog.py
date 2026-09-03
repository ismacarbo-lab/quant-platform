"""Normalized dataset catalog table (metadata only).

Revision ID: 0010_normalized_dataset_catalog
Revises: 0009_backtest_experiments
Create Date: 2026-08-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0010_normalized_dataset_catalog"
down_revision: str | None = "0009_backtest_experiments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "normalized_datasets",
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("normalized_dataset_id", sa.String(length=64), nullable=False),
        sa.Column("dataset_hash", sa.Text(), nullable=False),
        sa.Column("raw_dataset_hash", sa.Text(), nullable=True),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_snapshot_id", sa.String(length=64), nullable=True),
        sa.Column("source_replay_id", sa.String(length=64), nullable=True),
        sa.Column("adjustment_mode", sa.String(length=64), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("symbol_count", sa.Integer(), nullable=False),
        sa.Column("bar_count", sa.Integer(), nullable=False),
        sa.Column("adjusted_bar_count", sa.Integer(), nullable=False),
        sa.Column("applied_action_count", sa.Integer(), nullable=False),
        sa.Column("warning_count", sa.Integer(), nullable=False),
        sa.Column("error_count", sa.Integer(), nullable=False),
        sa.Column("is_reproducible", sa.Boolean(), nullable=False),
        sa.Column("is_usable", sa.Boolean(), nullable=False),
        sa.Column("artifacts", JSONB(), nullable=False),
        sa.Column("request", JSONB(), nullable=False),
        sa.Column("report_summary", JSONB(), nullable=False),
        sa.Column("manifest_hash", sa.Text(), nullable=False),
        sa.Column("package_version", sa.String(length=32), nullable=False),
        sa.Column("git_commit", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "registered_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "symbol_count >= 0", name="ck_normalized_datasets_symbol_count"
        ),
        sa.CheckConstraint("bar_count >= 0", name="ck_normalized_datasets_bar_count"),
        sa.CheckConstraint(
            "adjusted_bar_count >= 0", name="ck_normalized_datasets_adjusted_bar_count"
        ),
        sa.CheckConstraint(
            "applied_action_count >= 0",
            name="ck_normalized_datasets_applied_action_count",
        ),
        sa.CheckConstraint(
            "warning_count >= 0", name="ck_normalized_datasets_warning_count"
        ),
        sa.CheckConstraint(
            "error_count >= 0", name="ck_normalized_datasets_error_count"
        ),
        sa.CheckConstraint(
            "source_type IN ("
            "'local_artifacts', 'snapshot', 'replay', 'research_dataset')",
            name="ck_normalized_datasets_source_type",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "normalized_dataset_id", name="uq_normalized_datasets_normalized_dataset_id"
        ),
        sa.UniqueConstraint(
            "manifest_hash", name="uq_normalized_datasets_manifest_hash"
        ),
    )
    op.create_index(
        "ix_normalized_datasets_dataset_hash",
        "normalized_datasets",
        ["dataset_hash"],
    )
    op.create_index(
        "ix_normalized_datasets_raw_dataset_hash",
        "normalized_datasets",
        ["raw_dataset_hash"],
    )
    op.create_index(
        "ix_normalized_datasets_adjustment_mode",
        "normalized_datasets",
        ["adjustment_mode"],
    )
    op.create_index("ix_normalized_datasets_as_of", "normalized_datasets", ["as_of"])
    op.create_index(
        "ix_normalized_datasets_source_snapshot_id",
        "normalized_datasets",
        ["source_snapshot_id"],
    )
    op.create_index(
        "ix_normalized_datasets_source_replay_id",
        "normalized_datasets",
        ["source_replay_id"],
    )
    op.create_index(
        "ix_normalized_datasets_is_usable",
        "normalized_datasets",
        ["is_usable"],
    )
    op.create_index(
        "ix_normalized_datasets_created_at",
        "normalized_datasets",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_normalized_datasets_created_at", table_name="normalized_datasets")
    op.drop_index("ix_normalized_datasets_is_usable", table_name="normalized_datasets")
    op.drop_index(
        "ix_normalized_datasets_source_replay_id", table_name="normalized_datasets"
    )
    op.drop_index(
        "ix_normalized_datasets_source_snapshot_id", table_name="normalized_datasets"
    )
    op.drop_index("ix_normalized_datasets_as_of", table_name="normalized_datasets")
    op.drop_index(
        "ix_normalized_datasets_adjustment_mode", table_name="normalized_datasets"
    )
    op.drop_index(
        "ix_normalized_datasets_raw_dataset_hash", table_name="normalized_datasets"
    )
    op.drop_index(
        "ix_normalized_datasets_dataset_hash", table_name="normalized_datasets"
    )
    op.drop_table("normalized_datasets")
