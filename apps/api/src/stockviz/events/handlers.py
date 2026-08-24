"""Domain handlers for market/news/sentiment events.

Each function stages DB writes (bars, articles, scores, derived metrics,
outbox, inbox) and does **not** commit. Workers fetch from providers
*before* calling these, then commit the session and only then the Kafka offset.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date
from decimal import Decimal

from sqlmodel import Session, select

from stockviz.events.contracts import (
    MARKET_ANALYTICS_CONSUMER,
    MARKET_INGEST_CONSUMER,
    NEWS_INGEST_CONSUMER,
    NEWS_SENTIMENT_CONSUMER,
    SENTIMENT_AGGREGATE_CONSUMER,
    MarketBarsRefreshedEvent,
    MarketRefreshRequestedEvent,
    NewsArticleIngestedEvent,
    NewsRefreshRequestedEvent,
    NewsSentimentScoredEvent,
)
from stockviz.events.inbox import already_processed, try_record_processed
from stockviz.events.outbox import (
    enqueue_market_bars_refreshed,
    enqueue_news_article_ingested,
    enqueue_news_sentiment_scored,
)
from stockviz.models import NewsArticle, NewsSentiment
from stockviz.services.alerts import evaluate_pending_alerts
from stockviz.services.ingest.news import ArticleRecord, insert_new_articles
from stockviz.services.ingest.prices import DAILY_INTERVAL, BarRecord, upsert_bars
from stockviz.services.metrics import refresh_symbol_metrics
from stockviz.services.sentiment import get_provider
from stockviz.services.sentiment.base import SentimentInput, SentimentProvider, SentimentScore
from stockviz.services.sentiment.store import refresh_symbol_sentiment, score_articles

logger = logging.getLogger(__name__)

FetchBarsFn = Callable[[str, date | None], list[BarRecord]]
FetchNewsFn = Callable[[str, str], list[ArticleRecord]]


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
    if bars:
        upsert_bars(session, bars)
        latest = max(bars, key=lambda b: b.ts)
        enqueue_market_bars_refreshed(
            session,
            ticker=event.payload.ticker,
            interval=latest.interval or DAILY_INTERVAL,
            source=latest.source,
            bar_count=len(bars),
            latest_bar_at=latest.ts,
            latest_close=latest.close,
            request_event_id=event.event_id,
            occurred_at=event.occurred_at,
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


def persist_news_refresh(
    session: Session,
    event: NewsRefreshRequestedEvent,
    articles: list[ArticleRecord],
    *,
    consumer_name: str = NEWS_INGEST_CONSUMER,
) -> str:
    """Insert new articles + ``news.article.ingested`` per insert + inbox. No commit."""
    if already_processed(session, event_id=event.event_id, consumer_name=consumer_name):
        return "duplicate"
    inserted = insert_new_articles(session, articles)
    for article in inserted:
        if article.id is None or not article.ticker:
            continue
        enqueue_news_article_ingested(
            session,
            article_id=article.id,
            ticker=article.ticker,
            url=article.url,
            published_at=article.published_at,
            source=article.source,
            occurred_at=event.occurred_at,
        )
    if not try_record_processed(session, event_id=event.event_id, consumer_name=consumer_name):
        return "duplicate"
    return "applied"


def article_already_scored(session: Session, *, article_id: int, model: str) -> bool:
    row = session.exec(
        select(NewsSentiment).where(
            NewsSentiment.article_id == article_id,
            NewsSentiment.model == model,
        )
    ).first()
    return row is not None


def persist_article_sentiment(
    session: Session,
    event: NewsArticleIngestedEvent,
    result: SentimentScore | None,
    *,
    consumer_name: str = NEWS_SENTIMENT_CONSUMER,
) -> str:
    """Persist a score (if any) + ``news.sentiment.scored`` + inbox. No commit.

    ``result is None`` covers the null provider and provider skip: the inbox
    receipt is still written so redelivery does not retry, and no scored
    event is emitted. ``backfill_unscored`` can score later when a real
    provider is configured.
    """
    if already_processed(session, event_id=event.event_id, consumer_name=consumer_name):
        return "duplicate"
    article = session.get(NewsArticle, event.payload.article_id)
    if article is None:
        logger.warning(
            "sentiment worker: article_id=%s missing; recording inbox",
            event.payload.article_id,
        )
        try_record_processed(session, event_id=event.event_id, consumer_name=consumer_name)
        return "skipped"
    if result is not None:
        if article_already_scored(session, article_id=article.id, model=result.model):  # type: ignore[arg-type]
            logger.info("sentiment worker: article_id=%s already scored", article.id)
        else:
            score_articles(session, [article], provider=_SingleResultProvider(result), commit=False)
            enqueue_news_sentiment_scored(
                session,
                article_id=event.payload.article_id,
                ticker=event.payload.ticker,
                model=result.model,
                label=result.label,
                score=Decimal(str(result.score)),
                confidence=(None if result.confidence is None else Decimal(str(result.confidence))),
                occurred_at=event.occurred_at,
            )
    if not try_record_processed(session, event_id=event.event_id, consumer_name=consumer_name):
        return "duplicate"
    return "applied"


def apply_news_sentiment_scored(
    session: Session,
    event: NewsSentimentScoredEvent,
    *,
    consumer_name: str = SENTIMENT_AGGREGATE_CONSUMER,
) -> str:
    """Ticker-scoped sentiment aggregate + inbox. No commit."""
    if already_processed(session, event_id=event.event_id, consumer_name=consumer_name):
        return "duplicate"
    ticker = event.payload.ticker
    refresh_symbol_sentiment(
        session,
        model=event.payload.model,
        tickers=[ticker],
        commit=False,
    )
    if not try_record_processed(session, event_id=event.event_id, consumer_name=consumer_name):
        return "duplicate"
    return "applied"


class _SingleResultProvider:
    """Test/worker adapter: ``score_articles`` expects a provider interface."""

    def __init__(self, result: SentimentScore) -> None:
        self.name = result.model
        self._result = result

    def score(self, inputs: list[SentimentInput]) -> list[SentimentScore | None]:
        return [self._result for _ in inputs]


def score_one_article(
    article: NewsArticle,
    *,
    provider: SentimentProvider | None = None,
) -> SentimentScore | None:
    """Call the sentiment provider outside any DB transaction."""
    provider = provider or get_provider()
    if getattr(provider, "name", "") in ("", "none"):
        return None
    inputs = [
        SentimentInput(
            headline=article.title,
            summary=article.summary,
            ticker=article.ticker,
        )
    ]
    results = provider.score(inputs)
    return results[0] if results else None
