"""option strategies and leg covers (Phase 9.3)

``option_strategies`` groups legs opened from one template. Legs gain
``strategy_id`` and ``covering_leg_id`` (a short leg covered by a long leg of
the same strategy has ``cover = 'leg'``); a check keeps the two in step.

Revision ID: f2c8e4a6b135
Revises: e1b7d3f5a924
Create Date: 2026-11-16 21:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "f2c8e4a6b135"
down_revision: str | None = "e1b7d3f5a924"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHECK = "ck_options_positions_leg_cover_named"


def upgrade() -> None:
    op.create_table(
        "option_strategies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("portfolio_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("net_premium", sa.Numeric(20, 6), nullable=False),
        sa.Column("collateral", sa.Numeric(20, 6), nullable=False, server_default="0"),
        sa.Column("max_loss", sa.Numeric(20, 6), nullable=True),
        sa.Column("max_gain", sa.Numeric(20, 6), nullable=True),
        sa.Column("client_order_id", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True),
        sa.Column("opened_at", sa.DateTime(), nullable=False),
        sa.Column("settled_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["portfolio_id"], ["portfolios.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "portfolio_id", "client_order_id", name="uq_option_strategies_portfolio_client_order_id"
        ),
    )
    op.create_index(
        op.f("ix_option_strategies_user_id"), "option_strategies", ["user_id"], unique=False
    )
    op.create_index(
        op.f("ix_option_strategies_portfolio_id"),
        "option_strategies",
        ["portfolio_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_option_strategies_status"), "option_strategies", ["status"], unique=False
    )
    with op.batch_alter_table("options_positions") as batch:
        batch.add_column(sa.Column("strategy_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("covering_leg_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_options_positions_strategy_id", "option_strategies", ["strategy_id"], ["id"]
        )
        batch.create_foreign_key(
            "fk_options_positions_covering_leg_id",
            "options_positions",
            ["covering_leg_id"],
            ["id"],
        )
        batch.create_index("ix_options_positions_strategy_id", ["strategy_id"], unique=False)
        batch.create_check_constraint(CHECK, "(cover = 'leg') = (covering_leg_id IS NOT NULL)")


def downgrade() -> None:
    bind = op.get_bind()
    legs = bind.execute(
        sa.text("SELECT count(*) FROM options_positions WHERE strategy_id IS NOT NULL")
    ).scalar_one()
    if legs:
        raise RuntimeError(f"{legs} option leg(s) belong to strategies; downgrading drops them")
    with op.batch_alter_table("options_positions") as batch:
        batch.drop_constraint(CHECK, type_="check")
        batch.drop_index("ix_options_positions_strategy_id")
        batch.drop_constraint("fk_options_positions_covering_leg_id", type_="foreignkey")
        batch.drop_constraint("fk_options_positions_strategy_id", type_="foreignkey")
        batch.drop_column("covering_leg_id")
        batch.drop_column("strategy_id")
    op.drop_index(op.f("ix_option_strategies_status"), table_name="option_strategies")
    op.drop_index(op.f("ix_option_strategies_portfolio_id"), table_name="option_strategies")
    op.drop_index(op.f("ix_option_strategies_user_id"), table_name="option_strategies")
    op.drop_table("option_strategies")
