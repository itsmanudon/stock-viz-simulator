"""instrument_id NOT NULL wherever the ticker is (Phase 4.6a, contract step 1)

Every read goes through ``instrument_id`` since 4.4, so a row without one is
invisible. The identity triggers fill it before insert; this makes the
database refuse a row they could not fill (a ticker with no instrument).

Run ``stockviz.cli instrument-verify`` first: the upgrade stops, changing
nothing, if any of these tables still holds a NULL ``instrument_id``.

``news_articles`` keeps it nullable (its ticker is optional). The ticker
primary key of ``price_bars`` and the ``symbols.ticker`` foreign keys stay:
moving them needs the writers to set ``instrument_id`` themselves.

Revision ID: b4e2c7d9a610
Revises: a1eac5f9ee26
Create Date: 2026-11-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "b4e2c7d9a610"
down_revision: str | None = "a1eac5f9ee26"
branch_labels = None
depends_on = None

# Copied, not imported: a migration must not change when app code does.
REQUIRED_TABLES = (
    "alerts",
    "comments",
    "corporate_actions",
    "dividends",
    "earnings_events",
    "options_positions",
    "pending_orders",
    "portfolio_dividends",
    "positions",
    "price_bar_quarantine",
    "price_bars",
    "recommendations",
    "replay_sessions",
    "symbol_metrics",
    "trades",
    "watchlist_items",
)


def upgrade() -> None:
    bind = op.get_bind()
    missing = {}
    for table in REQUIRED_TABLES:
        count = bind.execute(
            sa.text(f"SELECT count(*) FROM {table} WHERE instrument_id IS NULL")
        ).scalar_one()
        if count:
            missing[table] = count
    if missing:
        raise RuntimeError(
            "instrument_id is NULL in "
            + ", ".join(f"{t} ({n})" for t, n in missing.items())
            + "; run `stockviz.cli instrument-check` and fix those rows first"
        )
    for table in REQUIRED_TABLES:
        op.alter_column(table, "instrument_id", existing_type=sa.BigInteger(), nullable=False)


def downgrade() -> None:
    for table in REQUIRED_TABLES:
        op.alter_column(table, "instrument_id", existing_type=sa.BigInteger(), nullable=True)
