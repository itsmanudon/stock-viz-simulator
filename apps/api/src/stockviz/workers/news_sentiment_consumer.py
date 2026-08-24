"""Consume ``news.article.ingested``: score, persist, emit sentiment.scored.

A null/no-op provider records the inbox receipt and does **not** emit
``news.sentiment.scored``. ``backfill_unscored`` can score later.

uv --directory apps/api run python -m stockviz.workers.news_sentiment_consumer --once
"""

from __future__ import annotations

import logging
import sys

from sqlmodel import Session

from stockviz.db import engine
from stockviz.events.contracts import (
    EVENT_TYPE_NEWS_ARTICLE_INGESTED,
    NEWS_SENTIMENT_CONSUMER,
    NEWS_TOPIC,
)
from stockviz.events.dispatcher import worker_main
from stockviz.events.handlers import persist_article_sentiment, score_one_article
from stockviz.events.outbox import parse_news_article_ingested
from stockviz.models import NewsArticle

logger = logging.getLogger(__name__)


def process_payload(payload: dict) -> str:
    event_type = payload.get("event_type")
    if event_type != EVENT_TYPE_NEWS_ARTICLE_INGESTED:
        logger.info("news sentiment ignoring event_type=%s", event_type)
        return "ignored"
    event = parse_news_article_ingested(payload)
    article: NewsArticle | None
    with Session(engine) as session:
        article = session.get(NewsArticle, event.payload.article_id)
        if article is not None:
            session.expunge(article)
    # Provider I/O happens with no row locks held.
    result = score_one_article(article) if article is not None else None
    with Session(engine) as session:
        status = persist_article_sentiment(session, event, result)
        session.commit()
    return status


def main(argv: list[str] | None = None) -> int:
    return worker_main(
        description="Consume stockviz.news.v1 news.article.ingested.",
        topic=NEWS_TOPIC,
        group_id=NEWS_SENTIMENT_CONSUMER,
        argv=argv,
        process=process_payload,
    )


if __name__ == "__main__":
    sys.exit(main())
