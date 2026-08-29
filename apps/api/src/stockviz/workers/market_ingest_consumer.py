"""Consume ``market.refresh.requested``: fetch bars, persist, emit bars.refreshed.

uv --directory apps/api run python -m stockviz.workers.market_ingest_consumer
uv --directory apps/api run python -m stockviz.workers.market_ingest_consumer --once
"""

from __future__ import annotations

import logging
import sys

from sqlmodel import Session

from stockviz.db import engine
from stockviz.events.contracts import (
    EVENT_TYPE_MARKET_REFRESH_REQUESTED,
    MARKET_INGEST_CONSUMER,
    MARKET_TOPIC,
)
from stockviz.events.dispatcher import worker_main
from stockviz.events.handlers import persist_market_refresh
from stockviz.events.outbox import parse_market_refresh_requested
from stockviz.services.ingest.prices import fetch_daily_bars
from stockviz.settings import get_settings

logger = logging.getLogger(__name__)


def fetch_bars_for_event(event: object) -> list:
    """Provider I/O. Tests monkeypatch this. A crash here does not write DB."""
    payload = event.payload  # type: ignore[attr-defined]
    settings = get_settings()
    since = payload.since.date() if payload.since is not None else None
    return fetch_daily_bars(
        payload.ticker,
        since=since,
        alpha_vantage_key=settings.alpha_vantage_key,
    )


def process_payload(payload: dict) -> str:
    event_type = payload.get("event_type")
    if event_type != EVENT_TYPE_MARKET_REFRESH_REQUESTED:
        logger.info("market ingest ignoring event_type=%s", event_type)
        return "ignored"
    event = parse_market_refresh_requested(payload)
    bars = fetch_bars_for_event(event)
    with Session(engine) as session:
        result = persist_market_refresh(session, event, bars)
        session.commit()
    return result


def main(argv: list[str] | None = None) -> int:
    return worker_main(
        description="Consume stockviz.market.v1 market.refresh.requested.",
        topic=MARKET_TOPIC,
        group_id=MARKET_INGEST_CONSUMER,
        argv=argv,
        process=process_payload,
    )


if __name__ == "__main__":
    sys.exit(main())
