"""Ingestion foundation bronze quality tables.

Revision ID: 0002_bronze
Revises: 0001_ingestion
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_bronze"
down_revision: str | None = "0001_ingestion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ingestion_runs",
        sa.Column(
            "accepted_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "ingestion_runs",
        sa.Column(
            "rejected_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_table(
        "raw_ingestion_records",
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("ingestion_run_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("record_index", sa.Integer(), nullable=False),
        sa.Column(
            "raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("record_index >= 0", name="ck_raw_ingestion_record_index"),
        sa.ForeignKeyConstraint(["ingestion_run_id"], ["ingestion_runs.id"]),
        sa.ForeignKeyConstraint(["source_id"], ["data_sources.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "ingestion_run_id",
            "record_index",
            name="uq_raw_ingestion_run_index",
        ),
    )
    op.create_index(
        "ix_raw_ingestion_source_hash",
        "raw_ingestion_records",
        ["source_id", "payload_hash"],
    )
    op.create_index(
        "ix_raw_ingestion_run_index",
        "raw_ingestion_records",
        ["ingestion_run_id", "record_index"],
    )
    op.create_table(
        "ingestion_errors",
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("ingestion_run_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("record_index", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column(
            "raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["ingestion_run_id"], ["ingestion_runs.id"]),
        sa.ForeignKeyConstraint(["source_id"], ["data_sources.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ingestion_errors_run",
        "ingestion_errors",
        ["ingestion_run_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_ingestion_errors_run", table_name="ingestion_errors")
    op.drop_table("ingestion_errors")
    op.drop_index("ix_raw_ingestion_run_index", table_name="raw_ingestion_records")
    op.drop_index("ix_raw_ingestion_source_hash", table_name="raw_ingestion_records")
    op.drop_table("raw_ingestion_records")
    op.drop_column("ingestion_runs", "rejected_count")
    op.drop_column("ingestion_runs", "accepted_count")
