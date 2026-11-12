"""cash per currency

Revision ID: a1eac5f9ee26
Revises: c9007a5002f5
Create Date: 2026-11-12 14:45:18.550027

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op


revision: str = "a1eac5f9ee26"
down_revision: str | None = "c9007a5002f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Phase 4.5b, cash per currency (design note option B). Additive: two new
    tables, and portfolios.base_currency defaulting to USD. Existing books hold
    no foreign cash (every sale so far converted to USD), so nothing moves."""
    op.create_table(
        "cash_balances",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("portfolio_id", sa.Integer(), nullable=False),
        sa.Column("currency", sqlmodel.sql.sqltypes.AutoString(length=3), nullable=False),
        sa.Column("amount", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.CheckConstraint("amount >= 0", name="ck_cash_balances_nonnegative"),
        sa.ForeignKeyConstraint(
            ["portfolio_id"],
            ["portfolios.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("portfolio_id", "currency", name="uq_cash_balances_portfolio_currency"),
    )
    op.create_index(
        op.f("ix_cash_balances_portfolio_id"), "cash_balances", ["portfolio_id"], unique=False
    )
    op.create_table(
        "fx_conversions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("portfolio_id", sa.Integer(), nullable=False),
        sa.Column("trade_id", sa.Integer(), nullable=True),
        sa.Column("from_currency", sqlmodel.sql.sqltypes.AutoString(length=3), nullable=False),
        sa.Column("to_currency", sqlmodel.sql.sqltypes.AutoString(length=3), nullable=False),
        sa.Column("from_amount", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("to_amount", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("rate", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("rate_date", sa.Date(), nullable=True),
        sa.Column("reason", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "from_amount > 0 AND to_amount > 0 AND rate > 0", name="ck_fx_conversions_positive"
        ),
        sa.ForeignKeyConstraint(
            ["portfolio_id"],
            ["portfolios.id"],
        ),
        sa.ForeignKeyConstraint(
            ["trade_id"],
            ["trades.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_fx_conversions_portfolio_id"), "fx_conversions", ["portfolio_id"], unique=False
    )
    op.create_index(
        op.f("ix_fx_conversions_trade_id"), "fx_conversions", ["trade_id"], unique=False
    )
    op.add_column(
        "portfolios",
        sa.Column("base_currency", sa.String(length=3), server_default="USD", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("portfolios", "base_currency")
    op.drop_index(op.f("ix_fx_conversions_trade_id"), table_name="fx_conversions")
    op.drop_index(op.f("ix_fx_conversions_portfolio_id"), table_name="fx_conversions")
    op.drop_table("fx_conversions")
    op.drop_index(op.f("ix_cash_balances_portfolio_id"), table_name="cash_balances")
    op.drop_table("cash_balances")
