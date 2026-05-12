"""HTTP response schemas.

Kept separate from the SQLModel tables so we can evolve the wire format
without churning the DB schema (or vice versa).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

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
    sentiment: Literal["positive", "neutral", "negative"] | None = None


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


class RecommendationOut(BaseModel):
    """One row from the ``recommendations`` table, joined with the symbol name."""

    model_config = ConfigDict(from_attributes=True)

    ticker: str
    name: str
    sector: str | None = None
    score: int
    rationale: list[str]
    computed_at: datetime


# ---------------------------------------------------------------------------
# Paper trading
# ---------------------------------------------------------------------------


class PositionOut(BaseModel):
    ticker: str
    name: str
    quantity: Decimal
    avg_cost: Decimal
    last_close: Decimal | None
    market_value: Decimal
    unrealized_pl: Decimal


class PortfolioOut(BaseModel):
    """Snapshot of the user's default portfolio used by /portfolio."""

    portfolio_id: int
    cash_balance: Decimal
    market_value: Decimal
    total_value: Decimal
    total_cost_basis: Decimal
    unrealized_pl: Decimal
    positions: list[PositionOut]


class TradeIn(BaseModel):
    """Request body for POST /v1/trades."""

    ticker: str
    side: Literal["buy", "sell"]
    quantity: Decimal


class TradeOut(BaseModel):
    """One executed trade — used by both POST response and /trades history."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    ticker: str
    side: Literal["buy", "sell"]
    quantity: Decimal
    price: Decimal
    ts: datetime


class PortfolioHistoryPointOut(BaseModel):
    """One row of the equity-curve series returned by /v1/portfolio/history."""

    model_config = ConfigDict(from_attributes=True)

    date: date
    nav: Decimal


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------


class AlertIn(BaseModel):
    """Request body for POST /v1/alerts."""

    ticker: str
    direction: Literal["above", "below"]
    target_price: Decimal


class AlertOut(BaseModel):
    """One alert row in API responses."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    ticker: str
    direction: Literal["above", "below"]
    target_price: Decimal
    created_at: datetime
    triggered_at: datetime | None
    dismissed_at: datetime | None


# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------


class WatchlistItemOut(BaseModel):
    """One ticker on the authenticated user's default watchlist."""

    ticker: str
    name: str
    sector: str | None
    added_at: datetime
    last_close: Decimal | None
