"""corporate actions and option shares per contract

Revision ID: 99489c8896a9
Revises: 992f3512eaf9
Create Date: 2026-11-12 11:43:22.426935

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op


revision: str = "99489c8896a9"
down_revision: str | None = "992f3512eaf9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Splits and their application to the ledger (Phase 4.2, #65).

    Two new tables, and one column on options_positions with a server default
    of 100, so every existing contract keeps its 100 shares. Additive only.
    """
    op.create_table(
        "corporate_actions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticker", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column("kind", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column("ex_date", sa.Date(), nullable=False),
        sa.Column("ratio_from", sa.Numeric(18, 6), nullable=False),
        sa.Column("ratio_to", sa.Numeric(18, 6), nullable=False),
        sa.Column("source", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column("recorded_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "ratio_from > 0 AND ratio_to > 0", name="ck_corporate_actions_ratio_positive"
        ),
        sa.ForeignKeyConstraint(["ticker"], ["symbols.ticker"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "ticker", "kind", "ex_date", name="uq_corporate_actions_ticker_kind_ex"
        ),
    )
    op.create_index("ix_corporate_actions_ticker", "corporate_actions", ["ticker"])
    op.create_index("ix_corporate_actions_ex_date", "corporate_actions", ["ex_date"])
    op.create_table(
        "corporate_action_applications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("action_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("applied_at", sa.DateTime(), nullable=False),
        sa.Column("summary", sqlmodel.sql.sqltypes.AutoString(length=500), nullable=False),
        sa.ForeignKeyConstraint(["action_id"], ["corporate_actions.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("action_id", "user_id", name="uq_corporate_action_applications"),
    )
    op.create_index(
        "ix_corporate_action_applications_action_id",
        "corporate_action_applications",
        ["action_id"],
    )
    op.create_index(
        "ix_corporate_action_applications_user_id", "corporate_action_applications", ["user_id"]
    )
    op.add_column(
        "options_positions",
        sa.Column("shares_per_contract", sa.Numeric(18, 6), nullable=False, server_default="100"),
    )


def downgrade() -> None:
    op.drop_column("options_positions", "shares_per_contract")
    op.drop_index(
        "ix_corporate_action_applications_user_id", table_name="corporate_action_applications"
    )
    op.drop_index(
        "ix_corporate_action_applications_action_id", table_name="corporate_action_applications"
    )
    op.drop_table("corporate_action_applications")
    op.drop_index("ix_corporate_actions_ex_date", table_name="corporate_actions")
    op.drop_index("ix_corporate_actions_ticker", table_name="corporate_actions")
    op.drop_table("corporate_actions")
