"""Consume ``news.sentiment.scored``: ticker-scoped rolling sentiment.

uv --directory apps/api run python -m stockviz.workers.sentiment_aggregate_consumer --once
"""

from __future__ import annotations

import sys
from typing import Any

from sqlmodel import Session

from stockviz.events.contracts import (
    EVENT_TYPE_NEWS_SENTIMENT_SCORED,
    NEWS_TOPIC,
    SENTIMENT_AGGREGATE_CONSUMER,
)
from stockviz.events.dispatcher import worker_main
from stockviz.events.handlers import apply_news_sentiment_scored
from stockviz.events.outbox import parse_news_sentiment_scored


def handle_sentiment_scored(session: Session, payload: dict[str, Any]) -> str:
    event = parse_news_sentiment_scored(payload)
    return apply_news_sentiment_scored(session, event)


def main(argv: list[str] | None = None) -> int:
    return worker_main(
        description="Consume stockviz.news.v1 news.sentiment.scored.",
        topic=NEWS_TOPIC,
        group_id=SENTIMENT_AGGREGATE_CONSUMER,
        argv=argv,
        handlers={EVENT_TYPE_NEWS_SENTIMENT_SCORED: handle_sentiment_scored},
    )


if __name__ == "__main__":
    sys.exit(main())
