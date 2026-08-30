"""Market-data models: symbols, price bars, news articles.

These are populated by the ingest pipeline and read by the public API.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, CheckConstraint, Index, Numeric
from sqlmodel import Column, Field, SQLModel

from stockviz._time import utcnow


class Symbol(SQLModel, table=True):
    """Tradable ticker.

    ``ticker`` is the natural primary key (string, e.g. ``AAPL``). We keep
    ``is_active`` so the ingest scheduler can skip delisted symbols without
    losing their history.
    """

    __tablename__ = "symbols"  # pyright: ignore[reportAssignmentType]

    ticker: str = Field(primary_key=True, max_length=16)
    name: str
    sector: str | None = None
    exchange: str | None = None
    # ISO-4217 currency the symbol trades in. USD for the historical universe;
    # non-USD symbols use the suffixed yfinance ticker (e.g. BARC.L -> GBP).
    currency: str = Field(default="USD", max_length=3, nullable=False)
    is_active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=utcnow, nullable=False)


class PriceBar(SQLModel, table=True):
    """OHLCV bar for a (ticker, ts, interval) triple.

    ``interval`` is part of the PK so we can store ``1d`` today and add
    ``1h`` later without a schema migration. Only ``1d`` is written today.
    """

    __tablename__ = "price_bars"  # pyright: ignore[reportAssignmentType]
    # The PK is (ticker, ts, interval), which does not serve the shape every
    # read actually uses: WHERE ticker = ? AND interval = ? ORDER BY ts DESC.
    # Postgres scans a btree in either direction, so a plain ascending index
    # on this column order covers it.
    __table_args__ = (
        Index("ix_price_bars_ticker_interval_ts", "ticker", "interval", "ts"),
        CheckConstraint(
            "adjustment_semantics IN ('unadjusted', 'split_adjusted', 'split_dividend_adjusted')",
            name="ck_price_bars_adjustment_semantics",
        ),
        CheckConstraint(
            "session_scope IN ('regular', 'provider_daily')",
            name="ck_price_bars_session_scope",
        ),
    )

    ticker: str = Field(foreign_key="symbols.ticker", primary_key=True, max_length=16)
    ts: datetime = Field(primary_key=True, index=True)
    interval: str = Field(primary_key=True, max_length=8)

    open: Decimal = Field(sa_column=Column(Numeric(18, 6), nullable=False))
    high: Decimal = Field(sa_column=Column(Numeric(18, 6), nullable=False))
    low: Decimal = Field(sa_column=Column(Numeric(18, 6), nullable=False))
    close: Decimal = Field(sa_column=Column(Numeric(18, 6), nullable=False))
    volume: int = Field(sa_column=Column(BigInteger, nullable=False))

    source: str | None = Field(default=None, max_length=32)
    adjustment_semantics: str = Field(default="split_adjusted", max_length=32, nullable=False)
    session_scope: str = Field(default="regular", max_length=32, nullable=False)


class QuarantinedPriceBar(SQLModel, table=True):
    """A bar that failed plausibility screening on ingest (F-011).

    Structurally valid (``low <= open, close <= high``, positive, finite) but
    implausible relative to context — an enormous intrabar range or a
    day-over-day move far past anything organic. Real markets do produce these
    (halt-resumes, biotech events, bank runs), so the bar is parked here for
    review rather than dropped. **Nothing prices off this table.**

    Each detection is a new row (surrogate ``id`` PK), so re-ingesting the same
    date leaves an audit trail instead of overwriting. See
    :mod:`stockviz.services.ingest.screening`.
    """

    __tablename__ = "price_bar_quarantine"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (Index("ix_price_bar_quarantine_ticker_ts", "ticker", "ts"),)

    id: int | None = Field(default=None, primary_key=True)
    ticker: str = Field(foreign_key="symbols.ticker", max_length=16)
    ts: datetime
    interval: str = Field(max_length=8)

    open: Decimal = Field(sa_column=Column(Numeric(18, 6), nullable=False))
    high: Decimal = Field(sa_column=Column(Numeric(18, 6), nullable=False))
    low: Decimal = Field(sa_column=Column(Numeric(18, 6), nullable=False))
    close: Decimal = Field(sa_column=Column(Numeric(18, 6), nullable=False))
    volume: int = Field(sa_column=Column(BigInteger, nullable=False))

    source: str | None = Field(default=None, max_length=32)
    adjustment_semantics: str | None = Field(default=None, max_length=32)
    session_scope: str | None = Field(default=None, max_length=32)
    # The close the bar was screened against, when one was known. NULL when the
    # bar was the first for its (ticker, interval) or the prior close was
    # itself quarantined.
    prev_close: Decimal | None = Field(default=None, sa_column=Column(Numeric(18, 6)))
    reason: str = Field(max_length=256)
    detected_at: datetime = Field(default_factory=utcnow, nullable=False)


class NewsArticle(SQLModel, table=True):
    """News article attached to a symbol.

    ``url`` is globally unique so we can dedupe re-ingests across sources.
    ``symbol`` is nullable — some general-market news isn't tied to one ticker.
    """

    __tablename__ = "news_articles"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    ticker: str | None = Field(
        default=None, foreign_key="symbols.ticker", index=True, max_length=16
    )

    title: str
    url: str = Field(unique=True, max_length=1024)
    source: str | None = Field(default=None, max_length=128)
    published_at: datetime = Field(index=True)
    summary: str | None = None
    image_url: str | None = Field(default=None, max_length=1024)

    # ``positive`` | ``neutral`` | ``negative`` | None. Filled by the headline
    # classifier on ingest when ANTHROPIC_API_KEY is set; otherwise stays None.
    sentiment: str | None = Field(default=None, max_length=16)

    created_at: datetime = Field(default_factory=utcnow, nullable=False)


class FxRate(SQLModel, table=True):
    """Daily FX rate quoted as USD per 1 unit of ``currency``.

    Stored relative to USD so conversions are multiplicative. USD itself is
    never stored — callers short-circuit to Decimal(1). ``date`` is the bar
    date; weekends/holidays are filled forward by reading the most recent
    rate on-or-before the requested date.
    """

    __tablename__ = "fx_rates"  # pyright: ignore[reportAssignmentType]

    currency: str = Field(primary_key=True, max_length=3)
    date: date_type = Field(primary_key=True, index=True)
    usd_rate: Decimal = Field(sa_column=Column(Numeric(18, 8), nullable=False))
    source: str | None = Field(default=None, max_length=32)
