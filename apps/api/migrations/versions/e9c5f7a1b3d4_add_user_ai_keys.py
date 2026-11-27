"""A8.7 users' own AI provider keys, encrypted (M11.2 BYOK).

Revision ID: e9c5f7a1b3d4
Revises: d8b4e6f0a2c3
Create Date: 2026-11-27 21:00:00.000000

``user_ai_keys``: one per user and provider, the key encrypted with
``APP_ENCRYPTION_KEY`` (never stored in clear), its last four characters, the
model and, for OpenAI-compatible endpoints, the base URL. Additive; the
downgrade refuses while a key is stored.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e9c5f7a1b3d4"
down_revision: str | None = "d8b4e6f0a2c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_ai_keys",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("provider", sa.String(length=24), nullable=False),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("key_last4", sa.String(length=4), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("base_url", sa.String(length=300), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "provider", name="uq_user_ai_keys_user_provider"),
        sa.CheckConstraint(
            "provider IN ('openai_compatible', 'anthropic')", name="ck_user_ai_keys_provider"
        ),
    )


def downgrade() -> None:
    stored = op.get_bind().execute(sa.text("SELECT count(*) FROM user_ai_keys")).scalar_one()
    if stored:
        raise RuntimeError(f"{stored} saved AI keys are stored; delete them before downgrading")
    op.drop_table("user_ai_keys")
