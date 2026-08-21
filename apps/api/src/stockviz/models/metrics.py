"""Precomputed per-symbol technical metrics.

The screener used to read ~260 bars per symbol and recompute RSI for the whole
universe on **every request** — roughly 8,300 rows scanned per call, with no
cache and no result cap. This table holds the same numbers, refreshed once a
day by the scheduler right after prices land, so the screener becomes one
indexed ``SELECT`` with WHERE clauses the database can actually use.

Momentum is deliberately *not* materialized: it needs only two closes, so the
screener computes it on demand with one windowed query and keeps accepting an
arbitrary ``momentum_days``. RSI and the 52-week range are the expensive parts,
and those live here.

The recommendations engine and the markets page can read the same rows rather
than each deriving their own, which also stops the surfaces from disagreeing
about a symbol's RSI.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Numeric
from sqlmodel import Column, Field, SQLModel

from stockviz._time import utcnow


class SymbolMetrics(SQLModel, table=True):
    """One row per symbol, overwritten by each refresh.

    Every metric is nullable: a symbol without enough history to compute RSI(14)
    or a 52-week range still gets a row, and the screener treats a NULL as
    "does not match this filter" rather than dropping the symbol entirely.
    """

    __tablename__ = "symbol_metrics"  # pyright: ignore[reportAssignmentType]

    ticker: str = Field(foreign_key="symbols.ticker", primary_key=True, max_length=16)

    # Date of the bar these metrics were computed from — lets a caller tell
    # stale rows from fresh ones without joining back to price_bars.
    as_of: date_type | None = Field(default=None, index=True)

    last_close: Decimal | None = Field(
        default=None, sa_column=Column(Numeric(18, 6), nullable=True)
    )
    rsi_14: float | None = Field(default=None, index=True)
    high_52w: Decimal | None = Field(default=None, sa_column=Column(Numeric(18, 6), nullable=True))
    low_52w: Decimal | None = Field(default=None, sa_column=Column(Numeric(18, 6), nullable=True))

    # Mean news sentiment over the trailing week, in [-1, 1]. Populated by the
    # sentiment aggregate pass; NULL when the symbol has no scored headlines.
    sentiment_7d: float | None = Field(default=None, index=True)
    sentiment_article_count: int = Field(default=0)

    computed_at: datetime = Field(default_factory=utcnow, nullable=False)
