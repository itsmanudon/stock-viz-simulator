"""add portfolio_snapshots

Revision ID: a91c4d2e7b8f
Revises: bfb5c1639ffd
Create Date: 2026-05-12 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "a91c4d2e7b8f"
down_revision: str | None = "bfb5c1639ffd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "portfolio_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("nav", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "date", name="uq_portfolio_snapshots_user_date"),
    )
    op.create_index(
        op.f("ix_portfolio_snapshots_user_id"), "portfolio_snapshots", ["user_id"], unique=False
    )
    op.create_index(
        op.f("ix_portfolio_snapshots_date"), "portfolio_snapshots", ["date"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_portfolio_snapshots_date"), table_name="portfolio_snapshots")
    op.drop_index(op.f("ix_portfolio_snapshots_user_id"), table_name="portfolio_snapshots")
    op.drop_table("portfolio_snapshots")
