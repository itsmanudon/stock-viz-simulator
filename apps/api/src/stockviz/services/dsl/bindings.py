"""Names a rule can read (A2.1): bar series, fundamentals and news."""

from __future__ import annotations

PRICE_SERIES = ("open", "high", "low", "close", "volume")
"""On every timeframe: daily bars, or weekly/monthly bars resampled from them."""

DELIVERY_SERIES = ("delivery_pct", "deliverable_qty")
"""Daily only, from ``eod_extras`` (NSE). Missing ("no data", never false)
until A1's NSE files are loaded."""

SERIES = PRICE_SERIES + DELIVERY_SERIES

FUNDAMENTAL_METRICS = (
    "market_cap",
    "enterprise_value",
    "pe",
    "pb",
    "ps",
    "ev_ebitda",
    "ev_revenue",
    "p_fcf",
    "dividend_yield",
    "gross_margin",
    "operating_margin",
    "net_margin",
    "roe",
    "roa",
    "roic_pretax",
    "debt_to_equity",
    "current_ratio",
    "payout_ratio",
    "revenue_growth",
    "net_income_growth",
)
"""``fundamental.<metric>``: the keys of ``services/fundamentals/valuation.py``,
as known on each bar's date."""

NEWS_FUNCTIONS = ("count",)
NEWS_SENTIMENTS = ("positive", "neutral", "negative", "mixed")
NEWS_MAX_DAYS = 365

TIMEFRAMES = ("weekly", "monthly")
INTERVAL_BY_TIMEFRAME = {"weekly": "1wk", "monthly": "1mo"}

__all__ = [
    "DELIVERY_SERIES",
    "FUNDAMENTAL_METRICS",
    "INTERVAL_BY_TIMEFRAME",
    "NEWS_FUNCTIONS",
    "NEWS_MAX_DAYS",
    "NEWS_SENTIMENTS",
    "PRICE_SERIES",
    "SERIES",
    "TIMEFRAMES",
]
