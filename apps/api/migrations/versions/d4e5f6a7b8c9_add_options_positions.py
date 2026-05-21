"""add options_positions

Revision ID: d4e5f6a7b8c9
Revises: c9d0e1f2a3b4
Create Date: 2026-05-21 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "d4e5f6a7b8c9"
down_revision: str | None = "c9d0e1f2a3b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "options_positions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("portfolio_id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(length=16), nullable=False),
        sa.Column("option_type", sa.String(length=4), nullable=False),
        sa.Column("strike", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("expiry", sa.Date(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("premium_paid", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("opened_at", sa.DateTime(), nullable=False),
        sa.Column("settled_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["portfolio_id"], ["portfolios.id"]),
        sa.ForeignKeyConstraint(["ticker"], ["symbols.ticker"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_options_positions_user_id"), "options_positions", ["user_id"], unique=False
    )
    op.create_index(
        op.f("ix_options_positions_portfolio_id"),
        "options_positions",
        ["portfolio_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_options_positions_ticker"), "options_positions", ["ticker"], unique=False
    )
    op.create_index(
        op.f("ix_options_positions_expiry"), "options_positions", ["expiry"], unique=False
    )
    op.create_index(
        op.f("ix_options_positions_status"), "options_positions", ["status"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_options_positions_status"), table_name="options_positions")
    op.drop_index(op.f("ix_options_positions_expiry"), table_name="options_positions")
    op.drop_index(op.f("ix_options_positions_ticker"), table_name="options_positions")
    op.drop_index(op.f("ix_options_positions_portfolio_id"), table_name="options_positions")
    op.drop_index(op.f("ix_options_positions_user_id"), table_name="options_positions")
    op.drop_table("options_positions")
