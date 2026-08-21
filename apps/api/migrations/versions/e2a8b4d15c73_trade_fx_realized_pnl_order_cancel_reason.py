"""trade fx_rate + realized_pnl, order cancel_reason, price_bars lookup index

- ``trades.fx_rate``      — USD-per-native-unit captured at fill time, so the
  trade log shows what a fill actually cost instead of re-converting history
  at today's rate.
- ``trades.realized_pnl`` — USD gain/loss vs. the weighted-average cost basis,
  written on sells.
- ``pending_orders.cancel_reason`` — why a triggered order could not fill, so
  cancellations aren't silent.
- ``ix_price_bars_ticker_interval_ts`` — the shape every latest-close,
  screener, and chart query actually uses. ``price_bars`` previously indexed
  ``ts`` alone plus the composite PK, neither of which serves
  ``WHERE ticker = ? AND interval = ? ORDER BY ts DESC``.

Revision ID: e2a8b4d15c73
Revises: d1f7a3c92b40
Create Date: 2026-08-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e2a8b4d15c73"
down_revision: str | None = "d1f7a3c92b40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("trades", sa.Column("fx_rate", sa.Numeric(18, 8), nullable=True))
    op.add_column("trades", sa.Column("realized_pnl", sa.Numeric(20, 6), nullable=True))
    op.add_column(
        "pending_orders", sa.Column("cancel_reason", sa.String(length=200), nullable=True)
    )
    op.create_index(
        "ix_price_bars_ticker_interval_ts",
        "price_bars",
        ["ticker", "interval", "ts"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_price_bars_ticker_interval_ts", table_name="price_bars")
    op.drop_column("pending_orders", "cancel_reason")
    op.drop_column("trades", "realized_pnl")
    op.drop_column("trades", "fx_rate")
