"""add replay_journals

1:1 user-authored decision journal for a ReplaySession (SIM-07).
Derived forensics (MAE/MFE, episodes) are computed, not stored.

Revision ID: d6a1b2c3e017
Revises: c8e5f1a2b3c4
Create Date: 2026-08-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d6a1b2c3e017"
down_revision: str | None = "c8e5f1a2b3c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "replay_journals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("thesis", sa.Text(), nullable=True),
        sa.Column("invalidation", sa.Text(), nullable=True),
        sa.Column("expected_holding_bars", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Integer(), nullable=True),
        sa.Column("reflection", sa.Text(), nullable=True),
        sa.Column("locked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["replay_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_replay_journals_session_id"), "replay_journals", ["session_id"], unique=True
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_replay_journals_session_id"), table_name="replay_journals")
    op.drop_table("replay_journals")
