"""ledger backstops and option client keys

Revision ID: 5d1b8e2c4a77
Revises: 3c7e5d9a1f20
Create Date: 2026-11-12 02:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "5d1b8e2c4a77"
down_revision: str | None = "3c7e5d9a1f20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, constraint name, condition) for every check this revision adds.
CHECKS = [
    ("portfolios", "ck_portfolios_cash_nonnegative", "cash_balance >= 0"),
    ("positions", "ck_positions_quantity_positive", "quantity > 0"),
    ("positions", "ck_positions_avg_cost_nonnegative", "avg_cost >= 0"),
    ("trades", "ck_trades_quantity_price_positive", "quantity > 0 AND price > 0"),
    (
        "pending_orders",
        "ck_pending_orders_amounts_positive",
        "quantity > 0 AND limit_price > 0",
    ),
    (
        "options_positions",
        "ck_options_positions_amounts_valid",
        "quantity > 0 AND strike > 0 AND premium_paid >= 0",
    ),
]


def upgrade() -> None:
    """Database backstops for the portfolio lock (audit LG-11).

    Every writer takes the portfolio lock and checks available cash and
    shares first, so none of these should ever fire. They turn a lost race or
    a new writer that skips the lock into an error instead of a wrong ledger.
    Production was checked read-only before this ran (12 Nov 2026): no row
    breaks any of them. A database that does have such rows fails here, and
    the rows need a look by hand before the upgrade.
    """
    with op.batch_alter_table("positions") as batch:
        batch.create_unique_constraint("uq_positions_portfolio_ticker", ["portfolio_id", "ticker"])
    for table, name, condition in CHECKS:
        with op.batch_alter_table(table) as batch:
            batch.create_check_constraint(name, condition)
    # Option opens get the client key trades and orders got in 3c7e5d9a1f20.
    with op.batch_alter_table("options_positions") as batch:
        batch.add_column(
            sa.Column("client_order_id", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True)
        )
        batch.create_unique_constraint(
            "uq_options_positions_portfolio_client_order_id", ["portfolio_id", "client_order_id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("options_positions") as batch:
        batch.drop_constraint("uq_options_positions_portfolio_client_order_id", type_="unique")
        batch.drop_column("client_order_id")
    for table, name, _condition in reversed(CHECKS):
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(name, type_="check")
    with op.batch_alter_table("positions") as batch:
        batch.drop_constraint("uq_positions_portfolio_ticker", type_="unique")
