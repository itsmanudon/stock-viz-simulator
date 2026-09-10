"""Add option terminal-event accounting and Trading Journal indexes.

``options_positions`` gains ``proceeds`` and ``realized_pnl``, written when a
contract leaves ``OPEN``. Only ``expired`` rows are backfilled: their loss is
exactly the premium paid, which is already stored. ``closed`` and ``exercised``
rows written before this migration keep NULL because their proceeds were never
persisted, and re-pricing them today would not be reproducible — the Trading
Journal excludes them rather than inventing a number.

The two composite indexes serve the Journal's month scans
(``trades`` by portfolio + timestamp, ``options_positions`` by user + settled).

Revision ID: a4d7c19f6e02
Revises: 2c1a9603e92b
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a4d7c19f6e02"
down_revision = "2c1a9603e92b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "options_positions",
        sa.Column("proceeds", sa.Numeric(20, 6), nullable=True),
    )
    op.add_column(
        "options_positions",
        sa.Column("realized_pnl", sa.Numeric(20, 6), nullable=True),
    )
    # `status` is a native enum on Postgres whose labels are the *member
    # names* (EXPIRED), while SQLite holds the StrEnum values (expired).
    # Comparing an upper-cased text cast matches both without a dialect branch.
    op.execute(
        """
        UPDATE options_positions
           SET proceeds = 0,
               realized_pnl = -premium_paid
         WHERE upper(CAST(status AS VARCHAR)) = 'EXPIRED'
           AND realized_pnl IS NULL
        """
    )
    op.create_index(
        "ix_options_positions_user_settled",
        "options_positions",
        ["user_id", "settled_at"],
    )
    op.create_index("ix_trades_portfolio_ts", "trades", ["portfolio_id", "ts"])


def downgrade() -> None:
    op.drop_index("ix_trades_portfolio_ts", table_name="trades")
    op.drop_index("ix_options_positions_user_settled", table_name="options_positions")
    op.drop_column("options_positions", "realized_pnl")
    op.drop_column("options_positions", "proceeds")
