"""HTTP response schemas.

Kept separate from the SQLModel tables so we can evolve the wire format
without churning the DB schema (or vice versa).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class SymbolOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ticker: str
    name: str
    sector: str | None = None
    exchange: str | None = None
    is_active: bool


class BarOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ts: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


class QuoteOut(BaseModel):
    ticker: str
    ts: datetime
    close: Decimal


class NewsArticleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticker: str | None
    title: str
    url: str
    source: str | None
    published_at: datetime
    summary: str | None
    image_url: str | None


class SymbolDetailOut(BaseModel):
    """Symbol metadata + most recent close, used on the ticker detail page."""

    model_config = ConfigDict(from_attributes=True)

    ticker: str
    name: str
    sector: str | None = None
    exchange: str | None = None
    is_active: bool
    latest: QuoteOut | None = None


class IndicatorPointOut(BaseModel):
    ts: datetime
    value: float


class MACDPointOut(BaseModel):
    ts: datetime
    macd: float
    signal: float
    histogram: float


class IndicatorsOut(BaseModel):
    """Indicator bundle keyed by indicator name.

    Scalar indicators (SMA/EMA/RSI) come back under ``series``; MACD has
    three aligned series so it gets its own field. The web app picks what
    to draw based on the names list it asked for.
    """

    ticker: str
    series: dict[str, list[IndicatorPointOut]] = {}
    macd: list[MACDPointOut] | None = None
