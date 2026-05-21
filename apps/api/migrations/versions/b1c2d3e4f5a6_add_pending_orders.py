"""add pending_orders table

Revision ID: b1c2d3e4f5a6
Revises: a3b4c5d6e7f8
Create Date: 2026-05-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "b1c2d3e4f5a6"
down_revision: str | None = "a3b4c5d6e7f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pending_orders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("portfolio_id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(length=16), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("order_type", sa.String(length=16), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("limit_price", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("filled_at", sa.DateTime(), nullable=True),
        sa.Column("fill_price", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.ForeignKeyConstraint(["portfolio_id"], ["portfolios.id"]),
        sa.ForeignKeyConstraint(["ticker"], ["symbols.ticker"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pending_orders_portfolio_id", "pending_orders", ["portfolio_id"])
    op.create_index("ix_pending_orders_ticker", "pending_orders", ["ticker"])
    op.create_index("ix_pending_orders_status", "pending_orders", ["status"])


def downgrade() -> None:
    op.drop_index("ix_pending_orders_status", "pending_orders")
    op.drop_index("ix_pending_orders_ticker", "pending_orders")
    op.drop_index("ix_pending_orders_portfolio_id", "pending_orders")
    op.drop_table("pending_orders")
