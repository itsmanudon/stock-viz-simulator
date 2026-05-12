"""add alerts table

Revision ID: c5d8e2a1f3b4
Revises: bfb5c1639ffd
Create Date: 2026-05-12 14:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "c5d8e2a1f3b4"
down_revision: str | None = "bfb5c1639ffd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(length=16), nullable=False),
        sa.Column("direction", sa.String(length=8), nullable=False),
        sa.Column("target_price", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("triggered_at", sa.DateTime(), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["ticker"], ["symbols.ticker"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_alerts_user_id"), "alerts", ["user_id"], unique=False)
    op.create_index(op.f("ix_alerts_ticker"), "alerts", ["ticker"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_alerts_ticker"), table_name="alerts")
    op.drop_index(op.f("ix_alerts_user_id"), table_name="alerts")
    op.drop_table("alerts")
