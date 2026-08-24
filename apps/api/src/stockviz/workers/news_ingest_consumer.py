"""Consume ``news.refresh.requested``: fetch articles, persist, emit ingested.

uv --directory apps/api run python -m stockviz.workers.news_ingest_consumer --once
"""

from __future__ import annotations

import logging
import sys

from sqlmodel import Session

from stockviz.db import engine
from stockviz.events.contracts import (
    EVENT_TYPE_NEWS_REFRESH_REQUESTED,
    NEWS_INGEST_CONSUMER,
    NEWS_TOPIC,
)
from stockviz.events.dispatcher import worker_main
from stockviz.events.handlers import persist_news_refresh
from stockviz.events.outbox import parse_news_refresh_requested
from stockviz.services.ingest.news import fetch_newsdata
from stockviz.settings import get_settings

logger = logging.getLogger(__name__)


def fetch_articles_for_event(event: object) -> list:
    """Provider I/O. Tests monkeypatch this."""
    payload = event.payload  # type: ignore[attr-defined]
    settings = get_settings()
    if not settings.newsdata_key:
        logger.warning("news ingest: NEWSDATA_KEY unset; recording empty fetch")
        return []
    return fetch_newsdata(
        api_key=settings.newsdata_key,
        query=payload.company_name,
        ticker=payload.ticker,
    )


def process_payload(payload: dict) -> str:
    event_type = payload.get("event_type")
    if event_type != EVENT_TYPE_NEWS_REFRESH_REQUESTED:
        logger.info("news ingest ignoring event_type=%s", event_type)
        return "ignored"
    event = parse_news_refresh_requested(payload)
    articles = fetch_articles_for_event(event)
    with Session(engine) as session:
        result = persist_news_refresh(session, event, articles)
        session.commit()
    return result


def main(argv: list[str] | None = None) -> int:
    return worker_main(
        description="Consume stockviz.news.v1 news.refresh.requested.",
        topic=NEWS_TOPIC,
        group_id=NEWS_INGEST_CONSUMER,
        argv=argv,
        process=process_payload,
    )


if __name__ == "__main__":
    sys.exit(main())
