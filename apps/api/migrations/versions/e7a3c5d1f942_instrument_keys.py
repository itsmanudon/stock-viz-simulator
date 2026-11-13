"""keys move from the ticker to the instrument (Phase 4.6b, contract step 2)

Writers set ``instrument_id`` themselves since this batch, so it can be part
of a primary key:

- ``price_bars``: (ticker, ts, interval) -> (instrument_id, ts, interval)
- ``symbol_metrics``: (ticker) -> (instrument_id); ticker stays unique
- ``watchlist_items``: (watchlist_id, ticker) -> (watchlist_id, instrument_id)

and the unique keys that held the ticker hold the instrument instead
(positions, dividends, portfolio dividends, corporate actions, earnings).
Ticker columns, their indexes and the ``symbols.ticker`` foreign keys stay.

Today a ticker names exactly one instrument, so the new keys are as unique
as the old ones. The upgrade checks that first and stops, changing nothing,
if any new key would repeat.

Revision ID: e7a3c5d1f942
Revises: d61f0a3b8c27
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e7a3c5d1f942"
down_revision: str | None = "d61f0a3b8c27"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, old name, old columns, new name, new columns, is primary key)
KEYS = (
    ("price_bars", "price_bars_pkey", ["ticker", "ts", "interval"],
     "price_bars_pkey", ["instrument_id", "ts", "interval"], True),
    ("symbol_metrics", "symbol_metrics_pkey", ["ticker"],
     "symbol_metrics_pkey", ["instrument_id"], True),
    ("watchlist_items", "watchlist_items_pkey", ["watchlist_id", "ticker"],
     "watchlist_items_pkey", ["watchlist_id", "instrument_id"], True),
    ("positions", "uq_positions_portfolio_ticker", ["portfolio_id", "ticker"],
     "uq_positions_portfolio_instrument", ["portfolio_id", "instrument_id"], False),
    ("dividends", "uq_dividends_ticker_ex_date", ["ticker", "ex_date"],
     "uq_dividends_instrument_ex_date", ["instrument_id", "ex_date"], False),
    ("portfolio_dividends", "uq_portfolio_dividends_portfolio_ticker_date",
     ["portfolio_id", "ticker", "ex_date"],
     "uq_portfolio_dividends_portfolio_instrument_date",
     ["portfolio_id", "instrument_id", "ex_date"], False),
    ("corporate_actions", "uq_corporate_actions_ticker_kind_ex", ["ticker", "kind", "ex_date"],
     "uq_corporate_actions_instrument_kind_ex", ["instrument_id", "kind", "ex_date"], False),
    ("earnings_events", "uq_earnings_events_identity", ["ticker", "event_date", "fiscal_period"],
     "uq_earnings_events_identity", ["instrument_id", "event_date", "fiscal_period"], False),
)  # fmt: skip


def _quoted(columns: list[str]) -> str:
    return ", ".join(f'"{c}"' for c in columns)


def _swap(table: str, drop: str, create: str, columns: list[str], primary: bool) -> None:
    op.drop_constraint(drop, table, type_="primary" if primary else "unique")
    if primary:
        op.create_primary_key(create, table, columns)
    else:
        op.create_unique_constraint(create, table, columns)


def upgrade() -> None:
    bind = op.get_bind()
    repeats = []
    for table, _old, _old_cols, _new, columns, _pk in KEYS:
        cols = _quoted(columns)
        count = bind.execute(
            sa.text(
                f"SELECT count(*) FROM (SELECT 1 FROM {table} GROUP BY {cols} "
                "HAVING count(*) > 1) d"
            )
        ).scalar_one()
        if count:
            repeats.append(f"{table} ({count})")
    if repeats:
        raise RuntimeError(
            "the instrument keys would repeat in " + ", ".join(repeats) + "; nothing changed"
        )
    for table, old, _old_cols, new, columns, primary in KEYS:
        _swap(table, old, new, columns, primary)
    op.create_unique_constraint("uq_symbol_metrics_ticker", "symbol_metrics", ["ticker"])


def downgrade() -> None:
    op.drop_constraint("uq_symbol_metrics_ticker", "symbol_metrics", type_="unique")
    for table, old, old_columns, new, _columns, primary in reversed(KEYS):
        _swap(table, new, old, old_columns, primary)
