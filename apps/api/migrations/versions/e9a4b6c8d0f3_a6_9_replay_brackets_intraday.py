"""A6.9 replay: bracket orders and intraday sessions.

Revision ID: e9a4b6c8d0f3
Revises: d1a6b11c2e40
Create Date: 2026-11-26 18:00:00.000000

- ``replay_orders`` gains ``parent_id`` (a bracket child's entry, cascade)
  and ``oco_group`` (the entry's id, shared by the entry and its stop and
  target). ``bracket`` joins the order types and ``pending`` the statuses (a
  child before its entry fills).
- ``replay_sessions`` gains ``interval`` (default ``1d``, so every existing
  session is daily as before) and ``feed`` (the minute feed of an intraday
  session; null for daily).

Additive. The downgrade refuses while a bracket, a pending order or an
intraday session is stored.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e9a4b6c8d0f3"
down_revision: str | None = "d1a6b11c2e40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_TYPE = "order_type IN ('limit', 'stop_loss', 'take_profit')"
NEW_TYPE = "order_type IN ('limit', 'stop_loss', 'take_profit', 'bracket')"
OLD_STATUS = "status IN ('open', 'filled', 'cancelled', 'rejected', 'expired')"
NEW_STATUS = "status IN ('pending', 'open', 'filled', 'cancelled', 'rejected', 'expired')"


def upgrade() -> None:
    op.add_column(
        "replay_sessions",
        sa.Column("interval", sa.String(length=8), nullable=False, server_default=sa.text("'1d'")),
    )
    op.add_column("replay_sessions", sa.Column("feed", sa.String(length=16), nullable=True))
    op.add_column("replay_orders", sa.Column("parent_id", sa.Integer(), nullable=True))
    op.add_column("replay_orders", sa.Column("oco_group", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_replay_orders_parent_id",
        "replay_orders",
        "replay_orders",
        ["parent_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_replay_orders_parent_id", "replay_orders", ["parent_id"])
    op.drop_constraint("ck_replay_orders_type", "replay_orders", type_="check")
    op.create_check_constraint("ck_replay_orders_type", "replay_orders", NEW_TYPE)
    op.drop_constraint("ck_replay_orders_status", "replay_orders", type_="check")
    op.create_check_constraint("ck_replay_orders_status", "replay_orders", NEW_STATUS)


def downgrade() -> None:
    conn = op.get_bind()
    held = conn.execute(
        sa.text(
            "SELECT (SELECT count(*) FROM replay_orders WHERE order_type = 'bracket' "
            "OR status = 'pending' OR parent_id IS NOT NULL) + "
            "(SELECT count(*) FROM replay_sessions WHERE interval <> '1d')"
        )
    ).scalar_one()
    if held:
        raise RuntimeError(
            "Refusing to downgrade: replay brackets or intraday sessions are stored. "
            "Delete them first."
        )
    op.drop_constraint("ck_replay_orders_status", "replay_orders", type_="check")
    op.create_check_constraint("ck_replay_orders_status", "replay_orders", OLD_STATUS)
    op.drop_constraint("ck_replay_orders_type", "replay_orders", type_="check")
    op.create_check_constraint("ck_replay_orders_type", "replay_orders", OLD_TYPE)
    op.drop_index("ix_replay_orders_parent_id", table_name="replay_orders")
    op.drop_constraint("fk_replay_orders_parent_id", "replay_orders", type_="foreignkey")
    op.drop_column("replay_orders", "oco_group")
    op.drop_column("replay_orders", "parent_id")
    op.drop_column("replay_sessions", "feed")
    op.drop_column("replay_sessions", "interval")
