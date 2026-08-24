"""APScheduler bootstrap.

Runs in-process alongside FastAPI (via lifespan). Every job is wrapped in
``single_instance``, which takes a Postgres advisory lock so a scale-out to two
API instances doesn't double-fire jobs that move money. If schedule volume ever
outgrows in-process, promote to a separate worker; for ~30 tickers a day that's
a long way off.

Market and news jobs enqueue durable outbox requests; they do not call
providers. Provider I/O lives in Kafka workers. Financial jobs (orders,
options, dividends, FX, snapshots) stay in-process by design.

News enqueue is skipped when no newsdata key is configured so local/CI
boots do not fill the outbox with work that cannot complete.
"""

from __future__ import annotations

import functools
import hashlib
import json
import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import text
from sqlmodel import Session, select

from stockviz._time import utcnow
from stockviz.db import engine
from stockviz.events.outbox import (
    enqueue_market_refresh_requested,
    enqueue_news_refresh_requested,
)
from stockviz.models import Symbol
from stockviz.services.ingest.fx import ingest_fx
from stockviz.services.ingest.seed import DEFAULT_COMPANIES_PATH
from stockviz.services.metrics import refresh_symbol_metrics
from stockviz.services.options import settle_expired_options
from stockviz.services.recommend import score_universe
from stockviz.services.sentiment.store import refresh_symbol_sentiment
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


def _advisory_key(job_id: str) -> int:
    """Stable signed 64-bit key for ``pg_try_advisory_lock`` from a job id."""
    digest = hashlib.sha256(job_id.encode("utf-8")).digest()[:8]
    return int.from_bytes(digest, "big", signed=True)


def single_instance(job_id: str) -> Callable[[Callable[[], None]], Callable[[], None]]:
    """Run the wrapped job only if this process wins a Postgres advisory lock.

    APScheduler runs in-process, so every API instance starts its own copy of
    the schedule. Without a lock a scale-out to two instances double-fires
    every job — which for order settlement and option expiry means filling the
    same order twice. The lock is session-scoped and released in ``finally``.

    Non-Postgres backends (SQLite in tests) don't have advisory locks, so the
    guard degrades to "always run".
    """

    def decorate(fn: Callable[[], None]) -> Callable[[], None]:
        @functools.wraps(fn)
        def wrapper() -> None:
            if engine.dialect.name != "postgresql":
                fn()
                return

            key = _advisory_key(job_id)
            with Session(engine) as lock_session:
                acquired = bool(
                    lock_session.exec(
                        text("SELECT pg_try_advisory_lock(:key)").bindparams(key=key)  # type: ignore[arg-type]
                    ).one()[0]
                )
                if not acquired:
                    logger.info("%s: another instance holds the lock, skipping", job_id)
                    return
                try:
                    fn()
                finally:
                    lock_session.exec(
                        text("SELECT pg_advisory_unlock(:key)").bindparams(key=key)  # type: ignore[arg-type]
                    )

        return wrapper

    return decorate


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


@single_instance("daily_price_refresh")
def daily_price_refresh() -> None:
    """Enqueue ``market.refresh.requested`` for every active symbol.

    Does not call yfinance / Alpha Vantage. The market-ingest worker performs
    provider I/O after the outbox publisher lands the request on Kafka.
    Duplicate schedules are safe: ingest upserts bars and the consumer inbox
    de-duplicates a redelivered event_id. A second scheduled request has a
    new event_id and may re-fetch; DB writes stay idempotent.
    """
    with _session_scope() as session:
        tickers = list(session.exec(select(Symbol.ticker).where(Symbol.is_active)).all())
        if not tickers:
            logger.info("daily_price_refresh: no active symbols, nothing to do")
            return
        for ticker in tickers:
            enqueue_market_refresh_requested(session, ticker=ticker, reason="daily")
        session.commit()
    logger.info("daily_price_refresh: enqueued %d market.refresh.requested", len(tickers))


@single_instance("hourly_top_movers")
def hourly_top_movers() -> None:
    """Enqueue hourly ``market.refresh.requested`` for ``TOP_TICKERS_HOURLY``.

    Does not fetch quotes and does not evaluate alerts. Alert evaluation runs
    in the market-analytics worker after ``market.bars.refreshed``.
    """
    with _session_scope() as session:
        for ticker in TOP_TICKERS_HOURLY:
            enqueue_market_refresh_requested(session, ticker=ticker, reason="hourly")
        session.commit()
    logger.info("hourly_top_movers: enqueued %d market.refresh.requested", len(TOP_TICKERS_HOURLY))


@single_instance("news_refresh")
def news_refresh() -> None:
    """Enqueue ``news.refresh.requested`` for every active symbol.

    Skipped if no newsdata key is configured (the worker cannot fetch). Does
    not call Newsdata.io and does not score sentiment.
    """
    settings = get_settings()
    if not settings.newsdata_key:
        logger.info("news_refresh: NEWSDATA_KEY not set, skipping")
        return
    names = _company_name_map()
    with _session_scope() as session:
        tickers = list(session.exec(select(Symbol.ticker).where(Symbol.is_active)).all())
        if not tickers:
            logger.info("news_refresh: no active symbols, nothing to do")
            return
        for ticker in tickers:
            enqueue_news_refresh_requested(
                session,
                ticker=ticker,
                company_name=names.get(ticker, ticker),
                reason="scheduled",
            )
        session.commit()
    logger.info("news_refresh: enqueued %d news.refresh.requested", len(tickers))


@single_instance("fx_refresh")
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


@single_instance("sentiment_aggregate_refresh")
def sentiment_aggregate_refresh() -> None:
    """Roll per-article sentiment into the per-symbol trailing average.

    Feeds the screener's sentiment filter, the recommendation engine's
    sentiment vote, and ``GET /v1/symbols/{ticker}/sentiment``. The ticker
    page does not yet overlay that series on the price chart.
    """
    with _session_scope() as session:
        updated = refresh_symbol_sentiment(session)
    logger.info("sentiment_aggregate_refresh: updated %d symbols", updated)


@single_instance("symbol_metrics_refresh")
def symbol_metrics_refresh() -> None:
    """Recompute the screener's precomputed RSI / 52-week metrics."""
    with _session_scope() as session:
        written = refresh_symbol_metrics(session)
    logger.info("symbol_metrics_refresh: wrote %d rows", written)


@single_instance("recommendations_refresh")
def recommendations_refresh() -> None:
    """Recompute the recommendation score for every active ticker."""
    with _session_scope() as session:
        results = score_universe(session, persist=True)
    logger.info("recommendations_refresh: scored %d tickers", len(results))


@single_instance("portfolio_snapshots_refresh")
def portfolio_snapshots_refresh() -> None:
    """Upsert today's NAV snapshot for every user who owns a portfolio."""
    today = utcnow().date()
    with _session_scope() as session:
        written = snapshot_user_navs(session, snapshot_date=today)
    logger.info("portfolio_snapshots_refresh: wrote %d snapshots for %s", written, today)


@single_instance("pending_orders_settlement")
def pending_orders_settlement() -> None:
    """Settle any pending orders triggered by today's EOD close.

    ``session_date`` is today, so an order is only filled when the symbol's
    latest bar is actually today's. If the 16:30 price refresh failed or ran
    long, orders stay pending rather than filling against yesterday's close.
    """
    today = utcnow().date()
    with _session_scope() as session:
        filled = settle_pending_orders(session, session_date=today)
    logger.info("pending_orders_settlement: filled %d order(s)", filled)


@single_instance("dividend_credit_refresh")
def dividend_credit_refresh() -> None:
    """Credit any dividends whose ex_date is today to eligible portfolios."""
    today = utcnow().date()
    with _session_scope() as session:
        credited = credit_due_dividends(session, credit_date=today)
    logger.info("dividend_credit_refresh: credited %d portfolio(s) for %s", credited, today)


@single_instance("options_expiry_refresh")
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

    # 4:50pm ET on weekdays — after prices, before the recommendations and
    # snapshot jobs that read the same numbers.
    scheduler.add_job(
        symbol_metrics_refresh,
        trigger=CronTrigger(day_of_week="mon-fri", hour=16, minute=50),
        id="symbol_metrics_refresh",
        replace_existing=True,
    )

    # 4:55pm ET on weekdays — after the metrics refresh, so the aggregate and
    # the technical metrics land on the same symbol_metrics rows in order.
    scheduler.add_job(
        sentiment_aggregate_refresh,
        trigger=CronTrigger(day_of_week="mon-fri", hour=16, minute=55),
        id="sentiment_aggregate_refresh",
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
