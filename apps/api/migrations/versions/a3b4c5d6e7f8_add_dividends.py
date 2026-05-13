"""add dividends and portfolio_dividends tables

Revision ID: a3b4c5d6e7f8
Revises: f1a2b3c4d5e6
Create Date: 2026-05-13 11:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "a3b4c5d6e7f8"
down_revision: str | None = "f1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dividends",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(length=16), nullable=False),
        sa.Column("ex_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.ForeignKeyConstraint(["ticker"], ["symbols.ticker"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ticker", "ex_date", name="uq_dividends_ticker_ex_date"),
    )
    op.create_index(op.f("ix_dividends_ticker"), "dividends", ["ticker"], unique=False)
    op.create_index(op.f("ix_dividends_ex_date"), "dividends", ["ex_date"], unique=False)

    op.create_table(
        "portfolio_dividends",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("portfolio_id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(length=16), nullable=False),
        sa.Column("ex_date", sa.Date(), nullable=False),
        sa.Column("amount_credited", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("credited_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["portfolio_id"], ["portfolios.id"]),
        sa.ForeignKeyConstraint(["ticker"], ["symbols.ticker"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "portfolio_id",
            "ticker",
            "ex_date",
            name="uq_portfolio_dividends_portfolio_ticker_date",
        ),
    )
    op.create_index(
        op.f("ix_portfolio_dividends_portfolio_id"),
        "portfolio_dividends",
        ["portfolio_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_portfolio_dividends_ticker"), "portfolio_dividends", ["ticker"], unique=False
    )
    op.create_index(
        op.f("ix_portfolio_dividends_ex_date"), "portfolio_dividends", ["ex_date"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_portfolio_dividends_ex_date"), table_name="portfolio_dividends")
    op.drop_index(op.f("ix_portfolio_dividends_ticker"), table_name="portfolio_dividends")
    op.drop_index(op.f("ix_portfolio_dividends_portfolio_id"), table_name="portfolio_dividends")
    op.drop_table("portfolio_dividends")
    op.drop_index(op.f("ix_dividends_ex_date"), table_name="dividends")
    op.drop_index(op.f("ix_dividends_ticker"), table_name="dividends")
    op.drop_table("dividends")
