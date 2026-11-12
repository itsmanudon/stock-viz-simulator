"""portfolio dividends in their own currency (Phase 4.5c)

A dividend is now paid into its own currency's cash. ``currency`` says which;
``base_value`` is the credit in the portfolio's base currency at the ex-date
rate. Every existing row was credited in USD to a USD portfolio, so the
backfill is ``currency = 'USD'`` and ``base_value = amount_credited``.

Revision ID: d61f0a3b8c27
Revises: b4e2c7d9a610
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d61f0a3b8c27"
down_revision: str | None = "b4e2c7d9a610"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "portfolio_dividends",
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="USD"),
    )
    op.add_column("portfolio_dividends", sa.Column("base_value", sa.Numeric(20, 6), nullable=True))
    op.execute("UPDATE portfolio_dividends SET base_value = amount_credited")
    op.alter_column(
        "portfolio_dividends", "base_value", existing_type=sa.Numeric(20, 6), nullable=False
    )


def downgrade() -> None:
    # The old meaning of amount_credited was the base (USD) value. The foreign
    # cash already paid stays in cash_balances.
    op.execute("UPDATE portfolio_dividends SET amount_credited = base_value")
    op.drop_column("portfolio_dividends", "base_value")
    op.drop_column("portfolio_dividends", "currency")
