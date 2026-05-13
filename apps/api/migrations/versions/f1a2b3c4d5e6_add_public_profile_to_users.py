"""add public_profile to users

Revision ID: f1a2b3c4d5e6
Revises: a91c4d2e7b8f, c5d8e2a1f3b4, e7f3b2a4d1c5
Create Date: 2026-05-13 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "f1a2b3c4d5e6"
down_revision: tuple[str, ...] | None = ("a91c4d2e7b8f", "c5d8e2a1f3b4", "e7f3b2a4d1c5")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("public_profile", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("users", "public_profile")
