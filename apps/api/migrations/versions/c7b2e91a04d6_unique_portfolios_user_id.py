"""one portfolio per user

Pending-order reservations serialize on the portfolio row. Concurrent first
use of ``ensure_default_portfolio`` could INSERT two portfolios for the same
user (``user_id`` was only indexed), giving each request a different lock.
The unique index makes the loser hit IntegrityError and re-read the winner.

Revision ID: c7b2e91a04d6
Revises: 9c41c7572753
Create Date: 2026-08-23
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "c7b2e91a04d6"
down_revision: str | None = "9c41c7572753"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_portfolios_user_id", table_name="portfolios")
    op.create_index("ix_portfolios_user_id", "portfolios", ["user_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_portfolios_user_id", table_name="portfolios")
    op.create_index("ix_portfolios_user_id", "portfolios", ["user_id"], unique=False)
