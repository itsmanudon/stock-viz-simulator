"""merge pending_orders + multi_currency/comments heads

Revision ID: 9ec122c43dc9
Revises: b1c2d3e4f5a6, c9d0e1f2a3b4
Create Date: 2026-05-18 02:18:59.367026

"""

from collections.abc import Sequence


revision: str = "9ec122c43dc9"
down_revision: str | None = ("b1c2d3e4f5a6", "c9d0e1f2a3b4")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
