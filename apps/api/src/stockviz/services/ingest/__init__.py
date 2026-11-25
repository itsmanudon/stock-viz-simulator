"""Ingest pipeline.

Pure ``fetch_*`` functions return lists of records and never touch the DB.
``upsert_*`` functions take a Session and write idempotently. Orchestrators
(``ingest_ticker``) compose the two and pick the
data source based on settings.

This split keeps unit tests dead simple: fixtures for the parser, an in-memory
SQLite for the writer, and a single thin orchestrator on top.
"""

from stockviz.services.ingest.bar_semantics import AdjustmentSemantics, SessionScope
from stockviz.services.ingest.prices import (
    BarRecord,
    fetch_alpha_vantage_daily,
    fetch_yfinance_daily,
    ingest_ticker,
    upsert_bars,
)
from stockviz.services.ingest.seed import seed_symbols

__all__ = [
    "AdjustmentSemantics",
    "BarRecord",
    "SessionScope",
    "fetch_alpha_vantage_daily",
    "fetch_yfinance_daily",
    "ingest_ticker",
    "seed_symbols",
    "upsert_bars",
]
