"""Instrument identity (Phase 4.3). See ``models/instrument.py``."""

TICKER_TABLES = (
    "alerts",
    "comments",
    "corporate_actions",
    "dividends",
    "earnings_events",
    "news_articles",
    "options_positions",
    "pending_orders",
    "portfolio_dividends",
    "positions",
    "price_bar_quarantine",
    "price_bars",
    "recommendations",
    "replay_sessions",
    "symbol_metrics",
    "trades",
    "watchlist_items",
)
"""Every table with a ``ticker`` foreign key, and so an ``instrument_id``.
The 4.3 migration keeps its own copy, as migrations must not import app code."""
