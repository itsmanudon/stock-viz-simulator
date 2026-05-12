"""Market-data models: symbols, price bars, news articles.

These are populated by the ingest pipeline and read by the public API.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Numeric
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
    is_active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=utcnow, nullable=False)


class PriceBar(SQLModel, table=True):
    """OHLCV bar for a (ticker, ts, interval) triple.

    ``interval`` is part of the PK so we can store ``1d`` today and add
    ``1h`` later without a schema migration. Phase 2 only writes ``1d``.
    """

    __tablename__ = "price_bars"  # pyright: ignore[reportAssignmentType]

    ticker: str = Field(foreign_key="symbols.ticker", primary_key=True, max_length=16)
    ts: datetime = Field(primary_key=True, index=True)
    interval: str = Field(primary_key=True, max_length=8)

    open: Decimal = Field(sa_column=Column(Numeric(18, 6), nullable=False))
    high: Decimal = Field(sa_column=Column(Numeric(18, 6), nullable=False))
    low: Decimal = Field(sa_column=Column(Numeric(18, 6), nullable=False))
    close: Decimal = Field(sa_column=Column(Numeric(18, 6), nullable=False))
    volume: int = Field(sa_column=Column(BigInteger, nullable=False))

    source: str | None = Field(default=None, max_length=32)


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
