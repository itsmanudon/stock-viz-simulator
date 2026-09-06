"""Capture native average cost at equity fill time; legacy values remain unknown.

Additive upgrade: nullable NUMERIC(18, 6), no default, update, or backfill.
PostgreSQL avoids a heap rewrite but still takes ACCESS EXCLUSIVE until commit.
Use deployment-level lock_timeout; see docs/TRADING_JOURNAL.md for rollout.
Downgrade drops captured basis values permanently; roll back application code
first and normally retain this additive column when reverting a deployment.
"""

from alembic import op
import sqlalchemy as sa

revision = "b6e8a20f4c31"
down_revision = "a4d7c19f6e02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("trades", sa.Column("avg_cost_at_fill", sa.Numeric(18, 6), nullable=True))


def downgrade() -> None:
    op.drop_column("trades", "avg_cost_at_fill")
