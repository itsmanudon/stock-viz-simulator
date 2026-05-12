"""add sentiment column to news_articles

Revision ID: e7f3b2a4d1c5
Revises: bfb5c1639ffd
Create Date: 2026-05-12 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "e7f3b2a4d1c5"
down_revision: str | None = "bfb5c1639ffd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "news_articles",
        sa.Column("sentiment", sa.String(length=16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("news_articles", "sentiment")
