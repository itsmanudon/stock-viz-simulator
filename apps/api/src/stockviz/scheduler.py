"""APScheduler bootstrap.

Runs in-process alongside FastAPI (via lifespan) for Phase 2. If the schedule
volume outgrows in-process we'll promote to a separate worker; for 25
tickers a day that's a long way off.

Jobs are no-ops when their data source has no API key configured — that way
the scheduler can start in CI / local dev without surprise network calls.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlmodel import Session, select

from stockviz.db import engine
from stockviz.models import Symbol
from stockviz.services.ingest.news import ingest_news_for_ticker
from stockviz.services.ingest.prices import ingest_ticker
from stockviz.services.ingest.seed import DEFAULT_COMPANIES_PATH
from stockviz.settings import get_settings

logger = logging.getLogger(__name__)

TOP_TICKERS_HOURLY = (
    "AAPL",
    "MSFT",
    "GOOGL",
    "AMZN",
    "META",
    "TSLA",
    "NVDA",
    "JPM",
    "V",
    "WMT",
)
"""The tickers refreshed hourly during market hours. Everything else is daily."""


@contextmanager
def _session_scope() -> Iterator[Session]:
    """Each scheduled job gets its own session — scheduler threads can't share one."""
    with Session(engine) as session:
        yield session


def _company_name_map() -> dict[str, str]:
    """Ticker -> company name, used as the newsdata.io query string.

    Falls back to an empty dict if companies.json is missing (e.g. in tests).
    """
    try:
        raw = json.loads(DEFAULT_COMPANIES_PATH.read_text(encoding="utf-8"))
        return {item["symbol"]: item["name"] for item in raw}
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        logger.warning("scheduler: could not load company names: %s", exc)
        return {}


def daily_price_refresh() -> None:
    """Pull EOD bars for every active symbol. Runs once a day after US close."""
    settings = get_settings()
    with _session_scope() as session:
        tickers = list(session.exec(select(Symbol.ticker).where(Symbol.is_active)).all())
    if not tickers:
        logger.info("daily_price_refresh: no active symbols, nothing to do")
        return
    logger.info("daily_price_refresh: %d tickers", len(tickers))
    for ticker in tickers:
        try:
            with _session_scope() as session:
                written = ingest_ticker(
                    session, ticker, alpha_vantage_key=settings.alpha_vantage_key
                )
                logger.info("daily_price_refresh: %s -> %d bars", ticker, written)
        except Exception:
            logger.exception("daily_price_refresh: failed for %s", ticker)


def hourly_top_movers() -> None:
    """Refresh the top-10 tickers more aggressively during market hours."""
    settings = get_settings()
    for ticker in TOP_TICKERS_HOURLY:
        try:
            with _session_scope() as session:
                ingest_ticker(session, ticker, alpha_vantage_key=settings.alpha_vantage_key)
        except Exception:
            logger.exception("hourly_top_movers: failed for %s", ticker)


def news_refresh() -> None:
    """Refresh news for every active symbol. Skipped if no newsdata key."""
    settings = get_settings()
    if not settings.newsdata_key:
        logger.info("news_refresh: NEWSDATA_KEY not set, skipping")
        return
    names = _company_name_map()
    with _session_scope() as session:
        tickers = list(session.exec(select(Symbol.ticker).where(Symbol.is_active)).all())
    for ticker in tickers:
        company = names.get(ticker, ticker)
        try:
            with _session_scope() as session:
                ingest_news_for_ticker(
                    session,
                    ticker=ticker,
                    company_name=company,
                    newsdata_key=settings.newsdata_key,
                )
        except Exception:
            logger.exception("news_refresh: failed for %s", ticker)


def build_scheduler() -> BackgroundScheduler:
    """Construct (but don't start) the scheduler. Caller owns lifecycle."""

    scheduler = BackgroundScheduler(timezone="America/New_York")

    # 4:30pm ET on weekdays — after the US equity market close at 4pm.
    scheduler.add_job(
        daily_price_refresh,
        trigger=CronTrigger(day_of_week="mon-fri", hour=16, minute=30),
        id="daily_price_refresh",
        replace_existing=True,
    )

    # Top of each hour, 10am - 4pm ET, weekdays.
    scheduler.add_job(
        hourly_top_movers,
        trigger=CronTrigger(day_of_week="mon-fri", hour="10-16", minute=0),
        id="hourly_top_movers",
        replace_existing=True,
    )

    # Every 4 hours.
    scheduler.add_job(
        news_refresh,
        trigger=CronTrigger(hour="*/4", minute=15),
        id="news_refresh",
        replace_existing=True,
    )

    return scheduler
