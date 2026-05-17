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
    currency: str = "USD"
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
    currency: str = "USD"
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
# Dividends
# ---------------------------------------------------------------------------


class DividendCreditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ticker: str
    ex_date: date
    amount_credited: Decimal
    credited_at: datetime


class ProjectedDividendOut(BaseModel):
    ticker: str
    projected_ex_date: date | None
    projected_amount: Decimal


class DividendSummaryOut(BaseModel):
    ytd_income: Decimal
    history: list[DividendCreditOut]
    projected: list[ProjectedDividendOut]


# ---------------------------------------------------------------------------
# Paper trading
# ---------------------------------------------------------------------------


class PositionOut(BaseModel):
    ticker: str
    name: str
    quantity: Decimal
    # ISO-4217 currency the symbol trades in.
    currency: str = "USD"
    # avg_cost is in the position's native currency.
    avg_cost: Decimal
    last_close: Decimal | None
    # Native-currency aggregates (unchanged regardless of display preference).
    market_value_native: Decimal = Decimal(0)
    unrealized_pl_native: Decimal = Decimal(0)
    # Same aggregates converted to the portfolio's display currency.
    market_value: Decimal
    unrealized_pl: Decimal


class PortfolioOut(BaseModel):
    """Snapshot of the user's default portfolio used by /portfolio.

    All top-level aggregates (cash_balance, market_value, totals) are in
    ``display_currency``. Per-position fields carry both native and converted
    amounts so the UI can show either.
    """

    portfolio_id: int
    display_currency: str = "USD"
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
    """One executed trade — used by both POST response and /trades history.

    ``price`` is the per-share fill price in the symbol's native currency.
    ``currency`` is that native currency; ``fx_rate`` is USD-per-unit at fill
    time (1 for USD symbols). ``total_native`` and ``total_usd`` are pre-
    computed so clients don't have to re-multiply.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    ticker: str
    side: Literal["buy", "sell"]
    quantity: Decimal
    price: Decimal
    ts: datetime
    currency: str = "USD"
    fx_rate: Decimal = Decimal(1)
    total_native: Decimal = Decimal(0)
    total_usd: Decimal = Decimal(0)


class PortfolioHistoryPointOut(BaseModel):
    """One row of the equity-curve series returned by /v1/portfolio/history."""

    model_config = ConfigDict(from_attributes=True)

    date: date
    nav: Decimal


# ---------------------------------------------------------------------------
# Leaderboard / profile
# ---------------------------------------------------------------------------


class LeaderboardEntryOut(BaseModel):
    rank: int
    user_id: int
    username: str
    return_pct: float
    portfolio_value: Decimal


class ProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    public_profile: bool
    display_currency: str = "USD"


class ProfilePatchIn(BaseModel):
    """All fields are optional — patch sends only what changes."""

    public_profile: bool | None = None
    display_currency: str | None = None


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


# ---------------------------------------------------------------------------
# Screener
# ---------------------------------------------------------------------------


class ScreenerResultOut(BaseModel):
    """One symbol that passed every active filter on /v1/symbols/screen."""

    ticker: str
    name: str
    sector: str | None = None
    exchange: str | None = None
    currency: str = "USD"
    last_close: Decimal
    rsi_14: float | None = None
    momentum_pct: float | None = None
    momentum_days: int | None = None
    high_52w: Decimal
    low_52w: Decimal


# ---------------------------------------------------------------------------
# Portfolio analytics
# ---------------------------------------------------------------------------


class SectorAllocationOut(BaseModel):
    sector: str
    market_value: Decimal
    pct: float


class TopMoverOut(BaseModel):
    ticker: str
    name: str
    sector: str | None
    unrealized_pl: Decimal
    return_pct: float


class CommentIn(BaseModel):
    """Request body for POST /v1/symbols/{ticker}/comments."""

    body: str
    parent_id: int | None = None


class CommentOut(BaseModel):
    """One comment in API responses.

    ``replies`` is populated by the GET endpoint when the comment is a
    top-level post — it contains its immediate children in chronological
    order. For deeper threads the UI is expected to render any further
    nesting by following ``parent_id``, but in v1 we only present a single
    level of indentation.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    user_name: str | None = None
    ticker: str
    body: str
    parent_id: int | None = None
    created_at: datetime
    replies: list[CommentOut] = []


class PortfolioAnalyticsOut(BaseModel):
    """Aggregated analytics for /v1/portfolio/analytics.

    Time-series metrics are ``None`` until at least two NAV snapshots have
    been recorded. ``history_days`` is the actual span observed (not the
    requested window) so the UI can label charts honestly.
    """

    display_currency: str = "USD"
    history_days: int
    total_return_pct: float | None
    annualised_return_pct: float | None
    sharpe_ratio: float | None
    max_drawdown_pct: float | None
    risk_free_rate: float
    sector_allocation: list[SectorAllocationOut]
    top_gainers: list[TopMoverOut]
    top_losers: list[TopMoverOut]
