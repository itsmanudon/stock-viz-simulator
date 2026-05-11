"""Ingest pipeline.

Pure ``fetch_*`` functions return lists of records and never touch the DB.
``upsert_*`` functions take a Session and write idempotently. Orchestrators
(``ingest_ticker``, ``ingest_news_for_ticker``) compose the two and pick the
data source based on settings.

This split keeps unit tests dead simple: fixtures for the parser, an in-memory
SQLite for the writer, and a single thin orchestrator on top.
"""

from stockviz.services.ingest.news import (
    ArticleRecord,
    fetch_newsdata,
    ingest_news_for_ticker,
    upsert_articles,
)
from stockviz.services.ingest.prices import (
    BarRecord,
    fetch_alpha_vantage_daily,
    fetch_yfinance_daily,
    ingest_ticker,
    upsert_bars,
)
from stockviz.services.ingest.seed import seed_symbols

__all__ = [
    "ArticleRecord",
    "BarRecord",
    "fetch_alpha_vantage_daily",
    "fetch_newsdata",
    "fetch_yfinance_daily",
    "ingest_news_for_ticker",
    "ingest_ticker",
    "seed_symbols",
    "upsert_articles",
    "upsert_bars",
]
