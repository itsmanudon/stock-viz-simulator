"""add client order ids

Revision ID: 3c7e5d9a1f20
Revises: fb895bc9eddc
Create Date: 2026-11-12 01:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "3c7e5d9a1f20"
down_revision: str | None = "fb895bc9eddc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Optional client keys on market trades and pending orders (#67, audit LG-10).

    Both columns are nullable and existing rows keep NULL, which a unique
    constraint never treats as a clash, so the upgrade touches no data.
    """
    with op.batch_alter_table("trades") as batch:
        batch.add_column(
            sa.Column("client_order_id", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True)
        )
        batch.create_unique_constraint(
            "uq_trades_portfolio_client_order_id", ["portfolio_id", "client_order_id"]
        )
    with op.batch_alter_table("pending_orders") as batch:
        batch.add_column(
            sa.Column("client_order_id", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True)
        )
        batch.create_unique_constraint(
            "uq_pending_orders_portfolio_client_order_id", ["portfolio_id", "client_order_id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("pending_orders") as batch:
        batch.drop_constraint("uq_pending_orders_portfolio_client_order_id", type_="unique")
        batch.drop_column("client_order_id")
    with op.batch_alter_table("trades") as batch:
        batch.drop_constraint("uq_trades_portfolio_client_order_id", type_="unique")
        batch.drop_column("client_order_id")
