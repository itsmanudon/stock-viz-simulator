"""add replay_sessions, replay_positions, replay_fills

Isolated ReplaySession over a frozen 1d PriceBar range (SIM-05). Replay
fills do not FK onto ``trades``. Child rows cascade if a session is deleted;
product code does not delete sessions.

Revision ID: c5f9d3e2b016
Revises: b4e8c2d1a905
Create Date: 2026-08-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c5f9d3e2b016"
down_revision: str | None = "b4e8c2d1a905"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "replay_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(length=16), nullable=False),
        sa.Column("profile_name", sa.String(length=64), nullable=False),
        sa.Column("model_version", sa.String(length=32), nullable=False),
        sa.Column("start_at", sa.DateTime(), nullable=False),
        sa.Column("current_at", sa.DateTime(), nullable=False),
        sa.Column("end_at", sa.DateTime(), nullable=False),
        sa.Column("starting_cash", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("cash_balance", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["ticker"], ["symbols.ticker"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_replay_sessions_user_id"), "replay_sessions", ["user_id"], unique=False
    )
    op.create_index(op.f("ix_replay_sessions_ticker"), "replay_sessions", ["ticker"], unique=False)
    op.create_index(
        op.f("ix_replay_sessions_current_at"), "replay_sessions", ["current_at"], unique=False
    )
    op.create_index(op.f("ix_replay_sessions_status"), "replay_sessions", ["status"], unique=False)

    op.create_table(
        "replay_positions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(length=16), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("avg_cost", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["replay_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "ticker", name="uq_replay_positions_session_ticker"),
    )
    op.create_index(
        op.f("ix_replay_positions_session_id"), "replay_positions", ["session_id"], unique=False
    )

    op.create_table(
        "replay_fills",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(length=16), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("fill_price", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("realized_pnl", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("profile_name", sa.String(length=64), nullable=False),
        sa.Column("model_version", sa.String(length=32), nullable=False),
        sa.Column("reference_price", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "assumptions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("market_interval", sa.String(length=16), nullable=False),
        sa.Column("order_type", sa.String(length=16), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["replay_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_replay_fills_session_id"), "replay_fills", ["session_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_replay_fills_session_id"), table_name="replay_fills")
    op.drop_table("replay_fills")
    op.drop_index(op.f("ix_replay_positions_session_id"), table_name="replay_positions")
    op.drop_table("replay_positions")
    op.drop_index(op.f("ix_replay_sessions_status"), table_name="replay_sessions")
    op.drop_index(op.f("ix_replay_sessions_current_at"), table_name="replay_sessions")
    op.drop_index(op.f("ix_replay_sessions_ticker"), table_name="replay_sessions")
    op.drop_index(op.f("ix_replay_sessions_user_id"), table_name="replay_sessions")
    op.drop_table("replay_sessions")
