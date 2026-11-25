"""Domain handlers for market events.

Each function stages DB writes (bars, derived metrics, outbox, inbox) and
does **not** commit. Workers fetch from providers *before* calling these,
then commit the session and only then the Kafka offset.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date

from sqlmodel import Session

from stockviz.events.contracts import (
    MARKET_ANALYTICS_CONSUMER,
    MARKET_INGEST_CONSUMER,
    MarketBarsRefreshedEvent,
    MarketRefreshRequestedEvent,
)
from stockviz.events.inbox import already_processed, try_record_processed
from stockviz.events.outbox import enqueue_market_bars_refreshed
from stockviz.services.alerts import evaluate_pending_alerts
from stockviz.services.ingest.prices import (
    DAILY_INTERVAL,
    BarRecord,
    record_quarantined_bars,
    screen_bars,
    write_accepted_bars,
)
from stockviz.services.metrics import refresh_symbol_metrics

logger = logging.getLogger(__name__)

FetchBarsFn = Callable[[str, date | None], list[BarRecord]]


def persist_market_refresh(
    session: Session,
    event: MarketRefreshRequestedEvent,
    bars: list[BarRecord],
    *,
    consumer_name: str = MARKET_INGEST_CONSUMER,
) -> str:
    """Upsert bars (if any) + ``market.bars.refreshed`` + inbox. No commit."""
    if already_processed(session, event_id=event.event_id, consumer_name=consumer_name):
        return "duplicate"
    # Screen provider data before it reaches price_bars (F-011). Implausible
    # bars are parked in price_bar_quarantine; the refreshed event must
    # describe only what actually landed in price_bars.
    accepted, quarantined = screen_bars(session, bars) if bars else ([], [])
    if quarantined:
        record_quarantined_bars(session, quarantined)
    if accepted:
        write_accepted_bars(session, accepted)
        latest = max(accepted, key=lambda b: b.ts)
        enqueue_market_bars_refreshed(
            session,
            ticker=event.payload.ticker,
            interval=latest.interval or DAILY_INTERVAL,
            source=latest.source,
            bar_count=len(accepted),
            latest_bar_at=latest.ts,
            latest_close=latest.close,
            request_event_id=event.event_id,
            occurred_at=event.occurred_at,
        )
    elif quarantined:
        logger.warning(
            "market ingest: %s — all %d provider bars failed screening; "
            "%d quarantined, request marked processed",
            event.payload.ticker,
            len(bars),
            len(quarantined),
        )
    else:
        logger.info(
            "market ingest: %s provider returned no bars; marking request processed",
            event.payload.ticker,
        )
    if not try_record_processed(session, event_id=event.event_id, consumer_name=consumer_name):
        return "duplicate"
    return "applied"


def apply_market_bars_refreshed(
    session: Session,
    event: MarketBarsRefreshedEvent,
    *,
    consumer_name: str = MARKET_ANALYTICS_CONSUMER,
) -> str:
    """Ticker-scoped metrics + alerts + inbox. No commit."""
    if already_processed(session, event_id=event.event_id, consumer_name=consumer_name):
        return "duplicate"
    ticker = event.payload.ticker
    refresh_symbol_metrics(session, tickers=[ticker], commit=False)
    evaluate_pending_alerts(session, ticker=ticker, commit=False)
    if not try_record_processed(session, event_id=event.event_id, consumer_name=consumer_name):
        return "duplicate"
    return "applied"
