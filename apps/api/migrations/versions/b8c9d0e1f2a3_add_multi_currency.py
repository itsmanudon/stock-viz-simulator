"""add multi-currency: symbols.currency, users.display_currency, fx_rates

Revision ID: b8c9d0e1f2a3
Revises: a3b4c5d6e7f8
Create Date: 2026-05-17 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "b8c9d0e1f2a3"
down_revision: str | None = "a3b4c5d6e7f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "symbols",
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="USD"),
    )
    op.add_column(
        "users",
        sa.Column("display_currency", sa.String(length=3), nullable=False, server_default="USD"),
    )

    op.create_table(
        "fx_rates",
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("usd_rate", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=True),
        sa.PrimaryKeyConstraint("currency", "date"),
    )
    op.create_index(op.f("ix_fx_rates_date"), "fx_rates", ["date"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_fx_rates_date"), table_name="fx_rates")
    op.drop_table("fx_rates")
    op.drop_column("users", "display_currency")
    op.drop_column("symbols", "currency")
