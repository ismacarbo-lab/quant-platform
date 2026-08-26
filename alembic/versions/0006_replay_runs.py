"""Replay run catalog table (metadata only).

Revision ID: 0006_replay_runs
Revises: 0005_catalog
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0006_replay_runs"
down_revision: str | None = "0005_catalog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "simulation_replay_runs",
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("replay_id", sa.String(length=64), nullable=False),
        sa.Column("stream_hash", sa.Text(), nullable=False),
        sa.Column("manifest_hash", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("dataset_snapshot_id", sa.String(length=64), nullable=True),
        sa.Column("dataset_content_hash", sa.Text(), nullable=True),
        sa.Column("package_version", sa.String(length=32), nullable=False),
        sa.Column("git_commit", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=True),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.Column("market_event_count", sa.Integer(), nullable=False),
        sa.Column("session_event_count", sa.Integer(), nullable=False),
        sa.Column("corporate_action_event_count", sa.Integer(), nullable=False),
        sa.Column("pre_known_event_count", sa.Integer(), nullable=False),
        sa.Column("warning_count", sa.Integer(), nullable=False),
        sa.Column("error_count", sa.Integer(), nullable=False),
        sa.Column("boundary_ok", sa.Boolean(), nullable=False),
        sa.Column("is_reproducible", sa.Boolean(), nullable=False),
        sa.Column("is_usable", sa.Boolean(), nullable=False),
        sa.Column("request", JSONB(), nullable=False),
        sa.Column("audit_summary", JSONB(), nullable=False),
        sa.Column("artifacts", JSONB(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "registered_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "event_count >= 0", name="ck_simulation_replay_runs_event_count"
        ),
        sa.CheckConstraint(
            "market_event_count >= 0",
            name="ck_simulation_replay_runs_market_event_count",
        ),
        sa.CheckConstraint(
            "session_event_count >= 0",
            name="ck_simulation_replay_runs_session_event_count",
        ),
        sa.CheckConstraint(
            "corporate_action_event_count >= 0",
            name="ck_simulation_replay_runs_ca_event_count",
        ),
        sa.CheckConstraint(
            "pre_known_event_count >= 0",
            name="ck_simulation_replay_runs_pre_known_event_count",
        ),
        sa.CheckConstraint(
            "warning_count >= 0", name="ck_simulation_replay_runs_warning_count"
        ),
        sa.CheckConstraint(
            "error_count >= 0", name="ck_simulation_replay_runs_error_count"
        ),
        sa.CheckConstraint(
            "source_type IN ('database', 'snapshot')",
            name="ck_simulation_replay_runs_source_type",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("replay_id", name="uq_simulation_replay_runs_replay_id"),
        sa.UniqueConstraint(
            "manifest_hash", name="uq_simulation_replay_runs_manifest_hash"
        ),
    )
    op.create_index(
        "ix_simulation_replay_runs_stream_hash",
        "simulation_replay_runs",
        ["stream_hash"],
    )
    op.create_index(
        "ix_simulation_replay_runs_source_type",
        "simulation_replay_runs",
        ["source_type"],
    )
    op.create_index(
        "ix_simulation_replay_runs_dataset_snapshot_id",
        "simulation_replay_runs",
        ["dataset_snapshot_id"],
    )
    op.create_index(
        "ix_simulation_replay_runs_created_at",
        "simulation_replay_runs",
        ["created_at"],
    )
    op.create_index(
        "ix_simulation_replay_runs_is_usable",
        "simulation_replay_runs",
        ["is_usable"],
    )
    op.create_index(
        "ix_simulation_replay_runs_boundary_ok",
        "simulation_replay_runs",
        ["boundary_ok"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_simulation_replay_runs_boundary_ok", table_name="simulation_replay_runs"
    )
    op.drop_index(
        "ix_simulation_replay_runs_is_usable", table_name="simulation_replay_runs"
    )
    op.drop_index(
        "ix_simulation_replay_runs_created_at", table_name="simulation_replay_runs"
    )
    op.drop_index(
        "ix_simulation_replay_runs_dataset_snapshot_id",
        table_name="simulation_replay_runs",
    )
    op.drop_index(
        "ix_simulation_replay_runs_source_type", table_name="simulation_replay_runs"
    )
    op.drop_index(
        "ix_simulation_replay_runs_stream_hash", table_name="simulation_replay_runs"
    )
    op.drop_table("simulation_replay_runs")
