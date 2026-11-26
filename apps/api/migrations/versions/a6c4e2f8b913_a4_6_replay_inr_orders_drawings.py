"""A4.6 (M9.1, M9.2): replay in any currency, resting orders, session drawings.

Additive:

- ``replay_sessions``: ``currency`` (default ``'USD'``, so every existing
  session, all USD by construction, keeps its meaning), ``fee_schedule``
  (default ``'none'``, what USD replay fills paid) and ``lag_override``
  (default false).
- ``replay_orders``: resting limit / stop-loss / take-profit orders.
- ``replay_fills``: ``fees`` (default 0: fills before A4.6 paid none),
  ``fee_lines`` and ``order_id`` (the resting order it filled, SET NULL).
- ``replay_drawings``: chart drawings made inside a session (own table, so
  the live chart and ``drawing()`` rules never read them).

The downgrade drops the new tables and columns (session orders, drawings and
fee amounts are lost; cash balances are not touched either way).

Revision ID: a6c4e2f8b913
Revises: e5a7c9b1d324
Create Date: 2026-11-26 18:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a6c4e2f8b913"
down_revision: str | None = "e5a7c9b1d324"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.add_column(
        "replay_sessions",
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="USD"),
    )
    op.add_column(
        "replay_sessions",
        sa.Column("fee_schedule", sa.String(length=40), nullable=False, server_default="none"),
    )
    op.add_column(
        "replay_sessions",
        sa.Column("lag_override", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_table(
        "replay_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Integer(),
            sa.ForeignKey("replay_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ticker", sa.String(length=16), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("order_type", sa.String(length=16), nullable=False),
        sa.Column("quantity", sa.Numeric(20, 6), nullable=False),
        sa.Column("limit_price", sa.Numeric(18, 6), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("placed_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "order_type IN ('limit', 'stop_loss', 'take_profit')",
            name="ck_replay_orders_type",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'filled', 'cancelled', 'rejected', 'expired')",
            name="ck_replay_orders_status",
        ),
    )
    op.create_index("ix_replay_orders_session_id", "replay_orders", ["session_id"])

    op.add_column(
        "replay_fills",
        sa.Column("fees", sa.Numeric(20, 6), nullable=False, server_default="0"),
    )
    op.add_column("replay_fills", sa.Column("fee_lines", _JSON, nullable=True))
    op.add_column(
        "replay_fills",
        sa.Column(
            "order_id",
            sa.Integer(),
            sa.ForeignKey("replay_orders.id", ondelete="SET NULL", name="fk_replay_fills_order_id"),
            nullable=True,
        ),
    )

    op.create_table(
        "replay_drawings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Integer(),
            sa.ForeignKey("replay_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("points", _JSON, nullable=False),
        sa.Column("style", _JSON, nullable=False),
        sa.Column("label", sa.String(length=80), nullable=True),
        sa.Column("locked", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_replay_drawings_session_id", "replay_drawings", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_replay_drawings_session_id", table_name="replay_drawings")
    op.drop_table("replay_drawings")
    op.drop_constraint("fk_replay_fills_order_id", "replay_fills", type_="foreignkey")
    op.drop_column("replay_fills", "order_id")
    op.drop_column("replay_fills", "fee_lines")
    op.drop_column("replay_fills", "fees")
    op.drop_index("ix_replay_orders_session_id", table_name="replay_orders")
    op.drop_table("replay_orders")
    op.drop_column("replay_sessions", "lag_override")
    op.drop_column("replay_sessions", "fee_schedule")
    op.drop_column("replay_sessions", "currency")
