"""public handles and display names (Phase 8.6, audit SR-12)

Revision ID: c4f6a8b0d923
Revises: a3e5c7f9b812
Create Date: 2026-11-13 06:50:00

Every existing user gets a random handle, so the leaderboard never needs the
email or the database id again.
"""

import secrets
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4f6a8b0d923"
down_revision: str | None = "a3e5c7f9b812"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("public_handle", sa.String(length=24), nullable=True))
    op.add_column("users", sa.Column("display_name", sa.String(length=40), nullable=True))
    conn = op.get_bind()
    taken: set[str] = set()
    for (user_id,) in conn.execute(sa.text("SELECT id FROM users ORDER BY id")):
        handle = f"trader-{secrets.token_hex(3)}"
        while handle in taken:
            handle = f"trader-{secrets.token_hex(3)}"
        taken.add(handle)
        conn.execute(
            sa.text("UPDATE users SET public_handle = :h WHERE id = :id"),
            {"h": handle, "id": user_id},
        )
    op.create_index("ix_users_public_handle", "users", ["public_handle"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_public_handle", table_name="users")
    op.drop_column("users", "display_name")
    op.drop_column("users", "public_handle")
