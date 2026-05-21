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

from stockviz._time import utcnow
from stockviz.db import engine
from stockviz.models import Symbol
from stockviz.services.alerts import evaluate_pending_alerts
from stockviz.services.ingest.fx import ingest_fx
from stockviz.services.ingest.news import ingest_news_for_ticker
from stockviz.services.ingest.prices import ingest_ticker
from stockviz.services.ingest.seed import DEFAULT_COMPANIES_PATH
from stockviz.services.options import settle_expired_options
from stockviz.services.recommend import score_universe
from stockviz.services.trading import (
    credit_due_dividends,
    settle_pending_orders,
    snapshot_user_navs,
)
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
    """Refresh the top-10 tickers more aggressively during market hours.

    After the fresh quotes land we re-evaluate pending price alerts so a user
    isn't waiting a full day for a notification.
    """
    settings = get_settings()
    for ticker in TOP_TICKERS_HOURLY:
        try:
            with _session_scope() as session:
                ingest_ticker(session, ticker, alpha_vantage_key=settings.alpha_vantage_key)
        except Exception:
            logger.exception("hourly_top_movers: failed for %s", ticker)
    try:
        with _session_scope() as session:
            triggered = evaluate_pending_alerts(session)
        if triggered:
            logger.info("hourly_top_movers: triggered %d alerts", triggered)
    except Exception:
        logger.exception("hourly_top_movers: alert evaluation failed")


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
                    anthropic_api_key=settings.anthropic_api_key,
                )
        except Exception:
            logger.exception("news_refresh: failed for %s", ticker)


def fx_refresh() -> None:
    """Pull today's FX rates for every non-USD currency in use.

    Runs after daily_price_refresh so snapshots that follow can convert
    market values at today's rate.
    """
    with _session_scope() as session:
        currencies = list(
            session.exec(
                select(Symbol.currency).where(Symbol.is_active, Symbol.currency != "USD").distinct()
            ).all()
        )
    currencies = [c for c in currencies if c]
    if not currencies:
        logger.info("fx_refresh: no non-USD currencies in use, nothing to do")
        return
    logger.info("fx_refresh: %d currencies", len(currencies))
    for ccy in currencies:
        try:
            with _session_scope() as session:
                written = ingest_fx(session, ccy)
                logger.info("fx_refresh: %s -> %d rates", ccy, written)
        except Exception:
            logger.exception("fx_refresh: failed for %s", ccy)


def recommendations_refresh() -> None:
    """Recompute the recommendation score for every active ticker."""
    with _session_scope() as session:
        results = score_universe(session, persist=True)
    logger.info("recommendations_refresh: scored %d tickers", len(results))


def portfolio_snapshots_refresh() -> None:
    """Upsert today's NAV snapshot for every user who owns a portfolio."""
    today = utcnow().date()
    with _session_scope() as session:
        written = snapshot_user_navs(session, snapshot_date=today)
    logger.info("portfolio_snapshots_refresh: wrote %d snapshots for %s", written, today)


def pending_orders_settlement() -> None:
    """Settle any pending orders triggered by today's EOD close."""
    with _session_scope() as session:
        filled = settle_pending_orders(session)
    logger.info("pending_orders_settlement: filled %d order(s)", filled)


def dividend_credit_refresh() -> None:
    """Credit any dividends whose ex_date is today to eligible portfolios."""
    today = utcnow().date()
    with _session_scope() as session:
        credited = credit_due_dividends(session, credit_date=today)
    logger.info("dividend_credit_refresh: credited %d portfolio(s) for %s", credited, today)


def options_expiry_refresh() -> None:
    """Settle every open option whose expiry has arrived (ITM exercise / OTM expiry)."""
    today = utcnow().date()
    with _session_scope() as session:
        settled = settle_expired_options(session, settle_date=today)
    logger.info("options_expiry_refresh: settled %d option(s) as of %s", settled, today)


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

    # 4:45pm ET on weekdays — after prices, before recommendations + snapshots
    # so today's FX rates are in the table when snapshots convert NAV.
    scheduler.add_job(
        fx_refresh,
        trigger=CronTrigger(day_of_week="mon-fri", hour=16, minute=45),
        id="fx_refresh",
        replace_existing=True,
    )

    # 5pm ET on weekdays — after the daily price refresh, so the algo has
    # today's close to score against.
    scheduler.add_job(
        recommendations_refresh,
        trigger=CronTrigger(day_of_week="mon-fri", hour=17, minute=0),
        id="recommendations_refresh",
        replace_existing=True,
    )

    # 5:15pm ET on weekdays — after recommendations, so today's close has
    # propagated through positions before we snapshot NAV.
    scheduler.add_job(
        portfolio_snapshots_refresh,
        trigger=CronTrigger(day_of_week="mon-fri", hour=17, minute=15),
        id="portfolio_snapshots_refresh",
        replace_existing=True,
    )

    # 9:30am ET on weekdays — credit dividends whose ex_date is today.
    scheduler.add_job(
        dividend_credit_refresh,
        trigger=CronTrigger(day_of_week="mon-fri", hour=9, minute=30),
        id="dividend_credit_refresh",
        replace_existing=True,
    )

    # 4:45pm ET on weekdays — settle pending orders against today's close.
    scheduler.add_job(
        pending_orders_settlement,
        trigger=CronTrigger(day_of_week="mon-fri", hour=16, minute=45),
        id="pending_orders_settlement",
        replace_existing=True,
    )

    # 5:30pm ET on weekdays — after the daily close has landed, settle any
    # options that expired today (ITM exercise / OTM worthless).
    scheduler.add_job(
        options_expiry_refresh,
        trigger=CronTrigger(day_of_week="mon-fri", hour=17, minute=30),
        id="options_expiry_refresh",
        replace_existing=True,
    )

    return scheduler
