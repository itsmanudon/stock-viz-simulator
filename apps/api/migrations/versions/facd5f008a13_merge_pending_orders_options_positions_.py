"""merge pending_orders + options_positions heads

Revision ID: facd5f008a13
Revises: b1c2d3e4f5a6, d4e5f6a7b8c9
Create Date: 2026-05-21 23:34:33.238866

"""

from collections.abc import Sequence



revision: str = "facd5f008a13"
down_revision: str | None = ("b1c2d3e4f5a6", "d4e5f6a7b8c9")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
