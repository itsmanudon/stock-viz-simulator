"""add generic price-bar financial semantics

Revision ID: f7b3d91a2c04
Revises: d6a1b2c3e017
Create Date: 2026-08-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f7b3d91a2c04"
down_revision: str | None = "d6a1b2c3e017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "price_bars",
        sa.Column(
            "adjustment_semantics",
            sa.String(length=32),
            server_default="split_adjusted",
            nullable=False,
        ),
    )
    op.add_column(
        "price_bars",
        sa.Column(
            "session_scope",
            sa.String(length=32),
            server_default="regular",
            nullable=False,
        ),
    )
    # Existing yfinance and seed/CSV rows are split-adjusted. The only
    # existing fallback whose parser intentionally emits raw OHLC is Alpha
    # Vantage, so preserve that distinction during the one-time backfill.
    op.execute(
        "UPDATE price_bars SET adjustment_semantics = 'unadjusted' WHERE source = 'alpha_vantage'"
    )
    op.create_check_constraint(
        "ck_price_bars_adjustment_semantics",
        "price_bars",
        "adjustment_semantics IN ('unadjusted', 'split_adjusted', 'split_dividend_adjusted')",
    )
    op.create_check_constraint(
        "ck_price_bars_session_scope",
        "price_bars",
        "session_scope IN ('regular', 'provider_daily')",
    )
    op.alter_column("price_bars", "adjustment_semantics", server_default=None)
    op.alter_column("price_bars", "session_scope", server_default=None)


def downgrade() -> None:
    op.drop_constraint("ck_price_bars_session_scope", "price_bars", type_="check")
    op.drop_constraint("ck_price_bars_adjustment_semantics", "price_bars", type_="check")
    op.drop_column("price_bars", "session_scope")
    op.drop_column("price_bars", "adjustment_semantics")
