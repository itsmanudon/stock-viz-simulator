"""A4.2 (M7.2): fees on paper trades.

Additive: three nullable columns on ``trades`` (``fees`` in the symbol's
currency, the ``fee_schedule`` name and the per-component ``fee_lines``).
Existing rows keep NULL: fills made before A4.2 are not recalculated. The
downgrade drops the columns (the fee amounts are lost; cash balances are not
touched either way).

Revision ID: c4f2a8e91b07
Revises: bb2ee29c23d3
Create Date: 2026-11-26 12:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c4f2a8e91b07"
down_revision: str | None = "bb2ee29c23d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("trades", sa.Column("fees", sa.Numeric(20, 6), nullable=True))
    op.add_column("trades", sa.Column("fee_schedule", sa.String(length=40), nullable=True))
    op.add_column(
        "trades",
        sa.Column(
            "fee_lines",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("trades", "fee_lines")
    op.drop_column("trades", "fee_schedule")
    op.drop_column("trades", "fees")
