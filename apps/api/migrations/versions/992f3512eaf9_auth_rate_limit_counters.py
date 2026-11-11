"""auth rate limit counters

Revision ID: 992f3512eaf9
Revises: 5d1b8e2c4a77
Create Date: 2026-11-12 01:41:18.486490

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "992f3512eaf9"
down_revision: str | None = "5d1b8e2c4a77"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Sign-in counters move from web memory to Postgres (audit OP-8). New table only."""
    op.create_table(
        "auth_rate_limits",
        sa.Column("key", sqlmodel.sql.sqltypes.AutoString(length=400), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("reset_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("auth_rate_limits")
