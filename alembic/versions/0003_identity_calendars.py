"""Instrument identity, calendars, and explicit PIT corrections.

Revision ID: 0003_identity
Revises: 0002_bronze
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_identity"
down_revision: str | None = "0002_bronze"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "market_calendars",
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_table(
        "market_sessions",
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("calendar_id", sa.Uuid(), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("open_time", sa.Time(), nullable=True),
        sa.Column("close_time", sa.Time(), nullable=True),
        sa.Column("is_open", sa.Boolean(), nullable=False),
        sa.Column("note", sa.String(length=256), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["calendar_id"], ["market_calendars.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "calendar_id", "session_date", name="uq_market_sessions_calendar_date"
        ),
    )
    op.create_index(
        "ix_market_sessions_calendar_date",
        "market_sessions",
        ["calendar_id", "session_date"],
    )
    op.drop_constraint("instruments_symbol_key", "instruments", type_="unique")
    op.add_column("instruments", sa.Column("calendar_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_instruments_calendar",
        "instruments",
        "market_calendars",
        ["calendar_id"],
        ["id"],
    )
    op.create_index("ix_instruments_symbol", "instruments", ["symbol"])
    # PostgreSQL 15+: NULL exchange/currency compare equal in the natural key.
    op.execute(
        sa.text(
            "ALTER TABLE instruments ADD CONSTRAINT uq_instruments_natural_key "
            "UNIQUE NULLS NOT DISTINCT "
            "(symbol, asset_class, exchange, currency)"
        )
    )
    op.create_table(
        "instrument_identifiers",
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("namespace", sa.String(length=64), nullable=False),
        sa.Column("value", sa.String(length=128), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to > valid_from",
            name="ck_instrument_identifiers_valid_range",
        ),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        sa.text(
            "ALTER TABLE instrument_identifiers "
            "ADD CONSTRAINT uq_instrument_identifiers_ns_value_from "
            "UNIQUE NULLS NOT DISTINCT (namespace, value, valid_from)"
        )
    )
    op.create_index(
        "ix_instrument_identifiers_instrument",
        "instrument_identifiers",
        ["instrument_id"],
    )
    op.add_column(
        "daily_bars",
        sa.Column(
            "is_correction",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "daily_bars", sa.Column("correction_reason", sa.Text(), nullable=True)
    )
    op.add_column(
        "daily_bars", sa.Column("supersedes_daily_bar_id", sa.Uuid(), nullable=True)
    )
    op.create_foreign_key(
        "fk_daily_bars_supersedes",
        "daily_bars",
        "daily_bars",
        ["supersedes_daily_bar_id"],
        ["id"],
    )
    op.create_check_constraint(
        "ck_daily_bars_supersedes_is_correction",
        "daily_bars",
        "supersedes_daily_bar_id IS NULL OR is_correction = true",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_daily_bars_supersedes_is_correction", "daily_bars", type_="check"
    )
    op.drop_constraint("fk_daily_bars_supersedes", "daily_bars", type_="foreignkey")
    op.drop_column("daily_bars", "supersedes_daily_bar_id")
    op.drop_column("daily_bars", "correction_reason")
    op.drop_column("daily_bars", "is_correction")
    op.drop_index(
        "ix_instrument_identifiers_instrument", table_name="instrument_identifiers"
    )
    op.drop_constraint(
        "uq_instrument_identifiers_ns_value_from",
        "instrument_identifiers",
        type_="unique",
    )
    op.drop_table("instrument_identifiers")
    op.execute(
        sa.text("ALTER TABLE instruments DROP CONSTRAINT uq_instruments_natural_key")
    )
    op.drop_index("ix_instruments_symbol", table_name="instruments")
    op.drop_constraint("fk_instruments_calendar", "instruments", type_="foreignkey")
    op.drop_column("instruments", "calendar_id")
    op.create_unique_constraint("instruments_symbol_key", "instruments", ["symbol"])
    op.drop_index("ix_market_sessions_calendar_date", table_name="market_sessions")
    op.drop_table("market_sessions")
    op.drop_table("market_calendars")
