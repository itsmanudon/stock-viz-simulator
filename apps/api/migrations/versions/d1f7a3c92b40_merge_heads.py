"""merge divergent heads (multi-currency/orders vs options/orders)

Two branch merges — ``9ec122c43dc9`` and ``facd5f008a13`` — were both left as
heads, so ``alembic upgrade head`` failed with "Multiple head revisions are
present". The API Dockerfile runs ``alembic upgrade head`` on boot, so this
also broke container start-up. This revision has no schema changes; it exists
only to unify the two lineages.

Revision ID: d1f7a3c92b40
Revises: 9ec122c43dc9, facd5f008a13
Create Date: 2026-08-21
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "d1f7a3c92b40"
down_revision: tuple[str, ...] | None = ("9ec122c43dc9", "facd5f008a13")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
