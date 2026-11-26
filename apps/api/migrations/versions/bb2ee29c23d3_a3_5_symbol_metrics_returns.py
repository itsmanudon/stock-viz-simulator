"""A3.5 (M2.7): price returns on symbol_metrics for the RS percentile.

Additive: four nullable float columns (percent return over 21, 63, 126 and
252 sessions), written by the nightly ``metrics`` job. The downgrade drops
them; the next ``metrics`` run refills them.

Revision ID: bb2ee29c23d3
Revises: d89bb4083e68
Create Date: 2026-11-26 03:27:03.677869

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "bb2ee29c23d3"
down_revision: str | None = "d89bb4083e68"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("symbol_metrics", sa.Column("return_1m", sa.Float(), nullable=True))
    op.add_column("symbol_metrics", sa.Column("return_3m", sa.Float(), nullable=True))
    op.add_column("symbol_metrics", sa.Column("return_6m", sa.Float(), nullable=True))
    op.add_column("symbol_metrics", sa.Column("return_12m", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("symbol_metrics", "return_12m")
    op.drop_column("symbol_metrics", "return_6m")
    op.drop_column("symbol_metrics", "return_3m")
    op.drop_column("symbol_metrics", "return_1m")
