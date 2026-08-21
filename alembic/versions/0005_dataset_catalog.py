"""Dataset snapshot catalog table (metadata only).

Revision ID: 0005_catalog
Revises: 0004_master
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0005_catalog"
down_revision: str | None = "0004_master"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dataset_snapshots",
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("snapshot_id", sa.String(length=64), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("quality_hash", sa.Text(), nullable=False),
        sa.Column("manifest_hash", sa.Text(), nullable=False),
        sa.Column("package_version", sa.String(length=32), nullable=False),
        sa.Column("git_commit", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("instrument_count", sa.Integer(), nullable=False),
        sa.Column("warning_count", sa.Integer(), nullable=False),
        sa.Column("error_count", sa.Integer(), nullable=False),
        sa.Column("is_reproducible", sa.Boolean(), nullable=False),
        sa.Column("is_usable", sa.Boolean(), nullable=False),
        sa.Column("dataset_request", JSONB(), nullable=False),
        sa.Column("quality_summary", JSONB(), nullable=False),
        sa.Column("artifacts", JSONB(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "registered_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("row_count >= 0", name="ck_dataset_snapshots_row_count"),
        sa.CheckConstraint(
            "instrument_count >= 0", name="ck_dataset_snapshots_instrument_count"
        ),
        sa.CheckConstraint(
            "warning_count >= 0", name="ck_dataset_snapshots_warning_count"
        ),
        sa.CheckConstraint("error_count >= 0", name="ck_dataset_snapshots_error_count"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_id", name="uq_dataset_snapshots_snapshot_id"),
        sa.UniqueConstraint("manifest_hash", name="uq_dataset_snapshots_manifest_hash"),
    )
    op.create_index(
        "ix_dataset_snapshots_content_hash", "dataset_snapshots", ["content_hash"]
    )
    op.create_index("ix_dataset_snapshots_as_of", "dataset_snapshots", ["as_of"])
    op.create_index(
        "ix_dataset_snapshots_window", "dataset_snapshots", ["start_time", "end_time"]
    )
    op.create_index(
        "ix_dataset_snapshots_git_commit", "dataset_snapshots", ["git_commit"]
    )
    op.create_index(
        "ix_dataset_snapshots_is_usable", "dataset_snapshots", ["is_usable"]
    )
    op.create_index(
        "ix_dataset_snapshots_error_count", "dataset_snapshots", ["error_count"]
    )


def downgrade() -> None:
    op.drop_index("ix_dataset_snapshots_error_count", table_name="dataset_snapshots")
    op.drop_index("ix_dataset_snapshots_is_usable", table_name="dataset_snapshots")
    op.drop_index("ix_dataset_snapshots_git_commit", table_name="dataset_snapshots")
    op.drop_index("ix_dataset_snapshots_window", table_name="dataset_snapshots")
    op.drop_index("ix_dataset_snapshots_as_of", table_name="dataset_snapshots")
    op.drop_index("ix_dataset_snapshots_content_hash", table_name="dataset_snapshots")
    op.drop_table("dataset_snapshots")
