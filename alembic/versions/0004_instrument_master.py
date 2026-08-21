"""Exchanges, corporate actions, session kinds, identifier namespaces.

Revision ID: 0004_master
Revises: 0003_identity
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0004_master"
down_revision: str | None = "0003_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "exchanges",
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("mic", sa.String(length=8), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("country", sa.String(length=8), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.add_column("instruments", sa.Column("exchange_id", sa.Uuid(), nullable=True))
    op.execute(
        sa.text(
            "INSERT INTO exchanges (id, code, timezone, created_at) "
            "SELECT gen_random_uuid(), distinct_exchange.exchange, 'UTC', now() "
            "FROM ("
            "  SELECT DISTINCT exchange FROM instruments "
            "  WHERE exchange IS NOT NULL"
            ") AS distinct_exchange"
        )
    )
    op.execute(
        sa.text(
            "UPDATE instruments AS instrument "
            "SET exchange_id = exchange.id "
            "FROM exchanges AS exchange "
            "WHERE instrument.exchange = exchange.code"
        )
    )
    op.execute(
        sa.text("ALTER TABLE instruments DROP CONSTRAINT uq_instruments_natural_key")
    )
    op.drop_column("instruments", "exchange")
    op.create_foreign_key(
        "fk_instruments_exchange",
        "instruments",
        "exchanges",
        ["exchange_id"],
        ["id"],
    )
    op.execute(
        sa.text(
            "ALTER TABLE instruments "
            "ADD CONSTRAINT uq_instruments_natural_key "
            "UNIQUE NULLS NOT DISTINCT "
            "(symbol, asset_class, exchange_id, currency)"
        )
    )
    op.create_index("ix_instruments_exchange", "instruments", ["exchange_id"])

    op.add_column(
        "market_sessions",
        sa.Column("session_kind", sa.String(length=32), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE market_sessions SET session_kind = "
            "CASE WHEN is_open THEN 'open' ELSE 'holiday' END"
        )
    )
    op.alter_column("market_sessions", "session_kind", nullable=False)
    op.create_check_constraint(
        "ck_market_sessions_kind",
        "market_sessions",
        "session_kind IN ('open', 'holiday', 'half_session', 'exceptional_close')",
    )
    op.create_check_constraint(
        "ck_market_sessions_kind_open",
        "market_sessions",
        "("
        "session_kind IN ('open', 'half_session') AND is_open = true"
        ") OR ("
        "session_kind IN ('holiday', 'exceptional_close') AND is_open = false"
        ")",
    )

    op.execute(
        sa.text(
            "UPDATE instrument_identifiers SET namespace = 'figi' "
            "WHERE namespace = 'figi_placeholder'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE instrument_identifiers SET namespace = 'isin' "
            "WHERE namespace = 'isin_placeholder'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE instrument_identifiers SET namespace = 'vendor_symbol' "
            "WHERE namespace = 'vendor_symbol_placeholder'"
        )
    )
    op.create_check_constraint(
        "ck_instrument_identifiers_namespace",
        "instrument_identifiers",
        "namespace IN ('isin', 'figi', 'cusip', 'local_symbol', 'vendor_symbol')",
    )

    op.add_column(
        "daily_bars",
        sa.Column("superseded_by_daily_bar_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_daily_bars_superseded_by",
        "daily_bars",
        "daily_bars",
        ["superseded_by_daily_bar_id"],
        ["id"],
    )
    op.create_check_constraint(
        "ck_daily_bars_superseded_by_not_self",
        "daily_bars",
        "superseded_by_daily_bar_id IS NULL OR superseded_by_daily_bar_id <> id",
    )
    op.create_check_constraint(
        "ck_daily_bars_supersedes_not_self",
        "daily_bars",
        "supersedes_daily_bar_id IS NULL OR supersedes_daily_bar_id <> id",
    )
    op.execute(
        sa.text(
            "UPDATE daily_bars AS original "
            "SET superseded_by_daily_bar_id = correction.id "
            "FROM daily_bars AS correction "
            "WHERE correction.supersedes_daily_bar_id = original.id"
        )
    )

    op.create_table(
        "corporate_actions",
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("action_type", sa.String(length=32), nullable=False),
        sa.Column("effective_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("quantity_before", sa.Numeric(28, 8), nullable=True),
        sa.Column("quantity_after", sa.Numeric(28, 8), nullable=True),
        sa.Column("cash_amount", sa.Numeric(28, 8), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=True),
        sa.Column("old_value", sa.String(length=64), nullable=True),
        sa.Column("new_value", sa.String(length=64), nullable=True),
        sa.Column("note", sa.String(length=256), nullable=True),
        sa.Column("details", JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action_type IN ('split', 'reverse_split', 'dividend', "
            "'symbol_change', 'delisting')",
            name="ck_corporate_actions_type",
        ),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_corporate_actions_instrument_effective",
        "corporate_actions",
        ["instrument_id", "effective_time"],
    )
    op.create_index(
        "ix_corporate_actions_instrument_available",
        "corporate_actions",
        ["instrument_id", "available_time"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_corporate_actions_instrument_available", table_name="corporate_actions"
    )
    op.drop_index(
        "ix_corporate_actions_instrument_effective", table_name="corporate_actions"
    )
    op.drop_table("corporate_actions")
    op.drop_constraint("ck_daily_bars_supersedes_not_self", "daily_bars", type_="check")
    op.drop_constraint(
        "ck_daily_bars_superseded_by_not_self", "daily_bars", type_="check"
    )
    op.drop_constraint("fk_daily_bars_superseded_by", "daily_bars", type_="foreignkey")
    op.drop_column("daily_bars", "superseded_by_daily_bar_id")
    op.drop_constraint(
        "ck_instrument_identifiers_namespace",
        "instrument_identifiers",
        type_="check",
    )
    op.drop_constraint("ck_market_sessions_kind_open", "market_sessions", type_="check")
    op.drop_constraint("ck_market_sessions_kind", "market_sessions", type_="check")
    op.drop_column("market_sessions", "session_kind")
    op.execute(
        sa.text("ALTER TABLE instruments DROP CONSTRAINT uq_instruments_natural_key")
    )
    op.drop_index("ix_instruments_exchange", table_name="instruments")
    op.drop_constraint("fk_instruments_exchange", "instruments", type_="foreignkey")
    op.add_column(
        "instruments", sa.Column("exchange", sa.String(length=32), nullable=True)
    )
    op.execute(
        sa.text(
            "UPDATE instruments AS instrument "
            "SET exchange = venue.code "
            "FROM exchanges AS venue "
            "WHERE instrument.exchange_id = venue.id"
        )
    )
    op.drop_column("instruments", "exchange_id")
    op.execute(
        sa.text(
            "ALTER TABLE instruments "
            "ADD CONSTRAINT uq_instruments_natural_key "
            "UNIQUE NULLS NOT DISTINCT "
            "(symbol, asset_class, exchange, currency)"
        )
    )
    op.drop_table("exchanges")
