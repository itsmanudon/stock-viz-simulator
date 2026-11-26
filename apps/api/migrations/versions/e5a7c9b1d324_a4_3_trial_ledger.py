"""A4.3 (M7.4): the automatic trial ledger and holdout unlocks.

Additive: two new tables. ``backtest_trials`` records every backtest run
(saved or not) by strategy hash, data fingerprint and user (NULL: the
anonymous pool); ``holdout_unlocks`` records a user's one-time unlock of a
strategy family's locked holdout. The downgrade drops both (the ledger and
unlock times are lost; no other table refers to them).

Revision ID: e5a7c9b1d324
Revises: c4f2a8e91b07
Create Date: 2026-11-26 18:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5a7c9b1d324"
down_revision: str | None = "c4f2a8e91b07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "backtest_trials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("family_key", sa.String(length=64), nullable=False),
        sa.Column("family_label", sa.String(length=120), nullable=False),
        sa.Column("strategy_hash", sa.String(length=64), nullable=False),
        sa.Column("data_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("observations", sa.Integer(), nullable=False),
        sa.Column("sharpe", sa.Float(), nullable=False),
        sa.Column("total_return", sa.Float(), nullable=False),
        sa.Column("runs", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_run_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_backtest_trials_family_user", "backtest_trials", ["family_key", "user_id"])
    op.create_index(
        "ix_backtest_trials_hash", "backtest_trials", ["strategy_hash", "data_fingerprint"]
    )
    op.create_index("ix_backtest_trials_created_at", "backtest_trials", ["created_at"])
    op.create_table(
        "holdout_unlocks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("family_key", sa.String(length=64), nullable=False),
        sa.Column("family_label", sa.String(length=120), nullable=False),
        sa.Column("holdout_from", sa.Date(), nullable=False),
        sa.Column("holdout_to", sa.Date(), nullable=False),
        sa.Column("unlocked_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "family_key", name="uq_holdout_unlocks_family"),
    )


def downgrade() -> None:
    op.drop_table("holdout_unlocks")
    op.drop_index("ix_backtest_trials_created_at", table_name="backtest_trials")
    op.drop_index("ix_backtest_trials_hash", table_name="backtest_trials")
    op.drop_index("ix_backtest_trials_family_user", table_name="backtest_trials")
    op.drop_table("backtest_trials")
