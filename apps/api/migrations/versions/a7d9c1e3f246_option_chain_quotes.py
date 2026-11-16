"""option chain snapshots (Phase 9.6)

Revision ID: a7d9c1e3f246
Revises: f2c8e4a6b135
Create Date: 2026-11-16 23:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7d9c1e3f246"
down_revision: str | None = "f2c8e4a6b135"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ID_TYPE = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "option_quotes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("instrument_id", ID_TYPE, nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("expiry", sa.Date(), nullable=False),
        sa.Column("strike", sa.Numeric(18, 6), nullable=False),
        sa.Column("option_type", sa.String(length=4), nullable=False),
        sa.Column("bid", sa.Numeric(18, 6), nullable=True),
        sa.Column("ask", sa.Numeric(18, 6), nullable=True),
        sa.Column("last", sa.Numeric(18, 6), nullable=True),
        sa.Column("price", sa.Numeric(18, 6), nullable=True),
        sa.Column("implied_volatility", sa.Float(), nullable=True),
        sa.Column("volume", sa.Integer(), nullable=True),
        sa.Column("open_interest", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "instrument_id",
            "snapshot_date",
            "expiry",
            "strike",
            "option_type",
            name="uq_option_quotes_contract_day",
        ),
    )
    op.create_index(
        op.f("ix_option_quotes_instrument_id"), "option_quotes", ["instrument_id"], unique=False
    )
    op.create_index(
        op.f("ix_option_quotes_snapshot_date"), "option_quotes", ["snapshot_date"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_option_quotes_snapshot_date"), table_name="option_quotes")
    op.drop_index(op.f("ix_option_quotes_instrument_id"), table_name="option_quotes")
    op.drop_table("option_quotes")
