"""risk limits (Phase 8.5): pre-trade caps a user sets, off until set

Revision ID: a3e5c7f9b812
Revises: d55cf5f51697
Create Date: 2026-11-13 06:45:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a3e5c7f9b812"
down_revision: str | None = "d55cf5f51697"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = (
    "max_position_pct",
    "max_order_pct",
    "max_sector_pct",
    "max_currency_pct",
    "max_var_pct",
)


def upgrade() -> None:
    op.create_table(
        "risk_limits",
        sa.Column("portfolio_id", sa.Integer(), nullable=False),
        *[sa.Column(name, sa.Numeric(6, 2), nullable=True) for name in COLUMNS],
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["portfolio_id"], ["portfolios.id"]),
        sa.PrimaryKeyConstraint("portfolio_id"),
        *[
            sa.CheckConstraint(
                f"{name} IS NULL OR ({name} > 0 AND {name} <= 100)",
                name=f"ck_risk_limits_{name}",
            )
            for name in COLUMNS
        ],
    )


def downgrade() -> None:
    op.drop_table("risk_limits")
