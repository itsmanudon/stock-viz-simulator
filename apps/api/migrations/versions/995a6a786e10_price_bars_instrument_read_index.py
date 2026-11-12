"""price bars instrument read index

Revision ID: 995a6a786e10
Revises: 686dcf74171b
Create Date: 2026-11-12 14:07:05.939793

"""

from collections.abc import Sequence

from alembic import op


revision: str = "995a6a786e10"
down_revision: str | None = "686dcf74171b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Reads of price_bars go by instrument from Phase 4.4: the same
    (key, interval, ts) shape as ix_price_bars_ticker_interval_ts, keyed on
    instrument_id. Additive; built in place (about 520k rows in production)."""
    op.create_index(
        "ix_price_bars_instrument_interval_ts",
        "price_bars",
        ["instrument_id", "interval", "ts"],
    )


def downgrade() -> None:
    op.drop_index("ix_price_bars_instrument_interval_ts", table_name="price_bars")
