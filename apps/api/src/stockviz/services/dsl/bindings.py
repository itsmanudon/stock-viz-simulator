"""Names a rule can read (A2.1): bar series, the venue index (A2.4),
fundamentals and news."""

from __future__ import annotations

PRICE_SERIES = ("open", "high", "low", "close", "volume")
"""On every timeframe: daily bars, or weekly/monthly bars resampled from them."""

DELIVERY_SERIES = ("delivery_pct", "deliverable_qty")
"""Daily only, from ``eod_extras`` (NSE). Missing ("no data", never false)
until A1's NSE files are loaded."""

INDEX_SERIES = ("index_close",)
"""The venue index's daily close on each bar (A2.4): ``^GSPC`` for US
listings, ``^NSEI`` for Indian ones (``event_study.BENCHMARK_BY_VENUE``),
forward-filled at most 5 bars, as ``rs()`` reads it. Point in time: a bar
sees the index close of its own date or earlier. On ``weekly.`` /
``monthly.`` it is the period's last index close."""

SERIES = PRICE_SERIES + DELIVERY_SERIES + INDEX_SERIES

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
    "INDEX_SERIES",
    "INTERVAL_BY_TIMEFRAME",
    "NEWS_FUNCTIONS",
    "NEWS_MAX_DAYS",
    "NEWS_SENTIMENTS",
    "PRICE_SERIES",
    "SERIES",
    "TIMEFRAMES",
]
