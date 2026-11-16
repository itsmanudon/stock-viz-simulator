"""option short legs: side and cover (Phase 9.2)

Every existing row is a long position, so ``side`` defaults to ``long`` and
``cover`` stays NULL. The check makes the database refuse a short leg with no
cover (no naked options) and a long leg that claims one.

Revision ID: e1b7d3f5a924
Revises: c4f6a8b0d923
Create Date: 2026-11-16 19:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e1b7d3f5a924"
down_revision: str | None = "c4f6a8b0d923"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHECK = "ck_options_positions_short_is_covered"


def upgrade() -> None:
    with op.batch_alter_table("options_positions") as batch:
        batch.add_column(
            sa.Column("side", sa.String(length=5), nullable=False, server_default="long")
        )
        batch.add_column(sa.Column("cover", sa.String(length=16), nullable=True))
        batch.create_check_constraint(
            CHECK,
            "(side = 'long' AND cover IS NULL) OR (side = 'short' AND cover IS NOT NULL)",
        )


def downgrade() -> None:
    # Refuse rather than silently turn a short leg into a long one.
    bind = op.get_bind()
    shorts = bind.execute(
        sa.text("SELECT count(*) FROM options_positions WHERE side = 'short'")
    ).scalar_one()
    if shorts:
        raise RuntimeError(
            f"{shorts} short option leg(s) exist; downgrading would make them long positions"
        )
    with op.batch_alter_table("options_positions") as batch:
        batch.drop_constraint(CHECK, type_="check")
        batch.drop_column("cover")
        batch.drop_column("side")
