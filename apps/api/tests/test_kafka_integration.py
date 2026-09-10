"""End-to-end outbox → Kafka → idempotent consumer (requires a broker)."""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlmodel import Session, select

from stockviz.events.activity import apply_trade_executed
from stockviz.events.contracts import (
    EVENT_TYPE_MARKET_BARS_REFRESHED,
    EVENT_TYPE_MARKET_REFRESH_REQUESTED,
    EVENT_TYPE_NEWS_ARTICLE_INGESTED,
    EVENT_TYPE_NEWS_REFRESH_REQUESTED,
    EVENT_TYPE_NEWS_SENTIMENT_SCORED,
    MARKET_TOPIC,
    NEWS_TOPIC,
    TRADES_TOPIC,
    TRADES_TOPIC_PARTITIONS,
)
from stockviz.events.handlers import (
    apply_market_bars_refreshed,
    apply_news_sentiment_scored,
    persist_article_sentiment,
    persist_market_refresh,
    persist_news_refresh,
)
from stockviz.events.outbox import (
    enqueue_market_refresh_requested,
    enqueue_news_refresh_requested,
    parse_market_bars_refreshed,
    parse_market_refresh_requested,
    parse_news_article_ingested,
    parse_news_refresh_requested,
    parse_news_sentiment_scored,
    parse_trade_executed,
    publish_batch,
)
from stockviz.events.producer import (
    ConfluentBrokerConsumer,
    ConfluentBrokerPublisher,
    ensure_event_topics,
    ensure_trades_topic,
)
from stockviz.models import (
    NewsArticle,
    NewsSentiment,
    OutboxEvent,
    PortfolioTradeActivity,
    PriceBar,
    Symbol,
    SymbolMetrics,
    TradeSide,
    User,
)
from stockviz.models.events import ConsumerInbox
from stockviz.services.ingest.bar_semantics import AdjustmentSemantics, SessionScope
from stockviz.services.ingest.news import ArticleRecord
from stockviz.services.ingest.prices import DAILY_INTERVAL, SOURCE_YFINANCE, BarRecord
from stockviz.services.sentiment.base import SentimentScore
from stockviz.services.trading import ensure_default_portfolio, execute_trade
from tests.pg_scratch import postgres_admin_url, scratch_postgres_engine

_KAFKA = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
_REQUIRED = os.environ.get("STOCKVIZ_KAFKA_REQUIRED") == "1"


def _broker_up() -> bool:
    try:
        from confluent_kafka.admin import AdminClient

        admin = AdminClient({"bootstrap.servers": _KAFKA})
        admin.list_topics(timeout=8)
        return True
    except Exception:
        return False


def _require_kafka() -> None:
    if _broker_up():
        return
    if _REQUIRED:
        pytest.fail(f"Kafka is required but unreachable at {_KAFKA}")
    pytest.skip("Kafka broker not reachable")


@pytest.mark.skipif(postgres_admin_url() is None, reason="DATABASE_URL is not PostgreSQL")
def test_trade_outbox_publisher_consumer_roundtrip() -> None:
    _require_kafka()
    group = f"stockviz.trade-activity.test.{uuid4().hex[:8]}"
    ensure_trades_topic(
        bootstrap_servers=_KAFKA, topic=TRADES_TOPIC, partitions=TRADES_TOPIC_PARTITIONS
    )

    with scratch_postgres_engine() as engine:
        with Session(engine) as session:
            user = User(email=f"kafka-{uuid4().hex}@stockviz.dev", name="Kafka")
            session.add(user)
            session.commit()
            session.refresh(user)
            assert user.id is not None
            session.add(Symbol(ticker="MSFT", name="Microsoft", currency="USD"))
            session.commit()
            session.add(
                PriceBar(
                    ticker="MSFT",
                    ts=datetime(2025, 4, 10),
                    interval="1d",
                    open=Decimal("100"),
                    high=Decimal("100"),
                    low=Decimal("100"),
                    close=Decimal("100"),
                    volume=1_000,
                    source="test",
                )
            )
            session.commit()
            portfolio = ensure_default_portfolio(session, user.id)
            assert portfolio.id is not None
            portfolio_id = portfolio.id
            execute_trade(
                session,
                user_id=user.id,
                ticker="MSFT",
                side=TradeSide.BUY,
                quantity=Decimal("2"),
            )
            pending = session.exec(select(OutboxEvent)).all()
            assert len(pending) == 1
            assert pending[0].published_at is None

        publisher = ConfluentBrokerPublisher(bootstrap_servers=_KAFKA)
        try:
            with Session(engine) as session:
                n = publish_batch(session, publisher, limit=50)
            assert n == 1
        finally:
            publisher.close()

        with Session(engine) as session:
            row = session.exec(select(OutboxEvent)).one()
            assert row.published_at is not None

        consumer = ConfluentBrokerConsumer(
            bootstrap_servers=_KAFKA,
            group_id=group,
            topic=TRADES_TOPIC,
        )
        try:
            polled = consumer.poll_json(20.0)
            assert polled is not None, "consumer did not receive the published trade.executed"
            msg, payload = polled
            with Session(engine) as session:
                event = parse_trade_executed(payload)
                apply_trade_executed(session, event)
                session.commit()
            consumer.commit(msg)
            # Redeliver-style second apply of the same payload.
            with Session(engine) as session:
                apply_trade_executed(session, parse_trade_executed(payload))
                session.commit()
                activity = session.get(PortfolioTradeActivity, portfolio_id)
                assert activity is not None
                assert activity.trade_count == 1
                receipts = session.exec(select(ConsumerInbox)).all()
                assert len(receipts) == 1
        finally:
            consumer.close()


def _poll_event(
    consumer: ConfluentBrokerConsumer,
    event_type: str,
    *,
    ticker: str | None = None,
    attempts: int = 25,
) -> dict:
    for _ in range(attempts):
        polled = consumer.poll_json(2.0)
        if polled is None:
            continue
        msg, payload = polled
        raw_inner = payload.get("payload")
        inner: dict = raw_inner if isinstance(raw_inner, dict) else {}
        matches_type = payload.get("event_type") == event_type
        matches_ticker = (
            ticker is None or inner.get("ticker") == ticker or payload.get("aggregate_id") == ticker
        )
        if matches_type and matches_ticker:
            consumer.commit(msg)
            return payload
        consumer.commit(msg)
    pytest.fail(f"did not receive {event_type} from Kafka (ticker={ticker})")


@pytest.mark.skipif(postgres_admin_url() is None, reason="DATABASE_URL is not PostgreSQL")
def test_market_event_pipeline_roundtrip() -> None:
    _require_kafka()
    ensure_event_topics(bootstrap_servers=_KAFKA)
    ticker = f"M{uuid4().hex[:4]}".upper()
    ingest_group = f"stockviz.market-ingest.test.{uuid4().hex[:8]}"
    analytics_group = f"stockviz.market-analytics.test.{uuid4().hex[:8]}"

    with scratch_postgres_engine() as engine:
        with Session(engine) as session:
            session.add(Symbol(ticker=ticker, name=ticker, currency="USD"))
            session.commit()
            enqueue_market_refresh_requested(session, ticker=ticker, reason="manual")
            session.commit()

        publisher = ConfluentBrokerPublisher(bootstrap_servers=_KAFKA)
        try:
            with Session(engine) as session:
                assert publish_batch(session, publisher, limit=50) >= 1

            ingest = ConfluentBrokerConsumer(
                bootstrap_servers=_KAFKA, group_id=ingest_group, topic=MARKET_TOPIC
            )
            try:
                payload = _poll_event(ingest, EVENT_TYPE_MARKET_REFRESH_REQUESTED, ticker=ticker)
            finally:
                ingest.close()

            event = parse_market_refresh_requested(payload)
            close = Decimal("123.45")
            # A gently rising close over 20 sessions. `high` has to track the
            # close (and `low` the open) or F-011 plausibility screening in
            # `upsert_bars` rejects the bar as structurally impossible and it
            # never reaches `price_bars`.
            bars = [
                BarRecord(
                    ticker=ticker,
                    ts=datetime(2024, 6, 3) + timedelta(days=i),
                    interval=DAILY_INTERVAL,
                    open=close,
                    high=close + Decimal(i),
                    low=close,
                    close=close + Decimal(i),
                    volume=Decimal("1000"),
                    source=SOURCE_YFINANCE,
                    adjustment_semantics=AdjustmentSemantics.SPLIT_ADJUSTED,
                    session_scope=SessionScope.REGULAR,
                )
                for i in range(20)
            ]
            with Session(engine) as session:
                persist_market_refresh(session, event, bars)
                session.commit()
                stored = session.exec(select(PriceBar).where(PriceBar.ticker == ticker)).all()
                assert len(stored) == 20

            with Session(engine) as session:
                assert publish_batch(session, publisher, limit=50) >= 1

            analytics = ConfluentBrokerConsumer(
                bootstrap_servers=_KAFKA, group_id=analytics_group, topic=MARKET_TOPIC
            )
            try:
                payload = _poll_event(analytics, EVENT_TYPE_MARKET_BARS_REFRESHED, ticker=ticker)
            finally:
                analytics.close()

            with Session(engine) as session:
                apply_market_bars_refreshed(session, parse_market_bars_refreshed(payload))
                session.commit()
                metrics = session.get(SymbolMetrics, ticker)
                assert metrics is not None
                assert metrics.last_close == close + Decimal(19)
        finally:
            publisher.close()


@pytest.mark.skipif(postgres_admin_url() is None, reason="DATABASE_URL is not PostgreSQL")
def test_news_sentiment_event_pipeline_roundtrip() -> None:
    _require_kafka()
    ensure_event_topics(bootstrap_servers=_KAFKA)
    ticker = f"N{uuid4().hex[:4]}".upper()
    ingest_group = f"stockviz.news-ingest.test.{uuid4().hex[:8]}"
    sentiment_group = f"stockviz.news-sentiment.test.{uuid4().hex[:8]}"
    agg_group = f"stockviz.sentiment-aggregate.test.{uuid4().hex[:8]}"
    url = f"https://example.test/kafka-{uuid4().hex}"

    with scratch_postgres_engine() as engine:
        with Session(engine) as session:
            session.add(Symbol(ticker=ticker, name=ticker, currency="USD"))
            session.commit()
            enqueue_news_refresh_requested(
                session, ticker=ticker, company_name=f"{ticker} Corp", reason="manual"
            )
            session.commit()

        publisher = ConfluentBrokerPublisher(bootstrap_servers=_KAFKA)
        try:
            with Session(engine) as session:
                assert publish_batch(session, publisher, limit=50) >= 1

            ingest = ConfluentBrokerConsumer(
                bootstrap_servers=_KAFKA, group_id=ingest_group, topic=NEWS_TOPIC
            )
            try:
                payload = _poll_event(ingest, EVENT_TYPE_NEWS_REFRESH_REQUESTED, ticker=ticker)
            finally:
                ingest.close()

            event = parse_news_refresh_requested(payload)
            with Session(engine) as session:
                persist_news_refresh(
                    session,
                    event,
                    [
                        ArticleRecord(
                            ticker=ticker,
                            title="Beat estimates",
                            url=url,
                            source="test",
                            published_at=datetime.now() - timedelta(hours=1),
                            summary="strong quarter",
                            image_url=None,
                        )
                    ],
                )
                session.commit()
                assert session.exec(select(NewsArticle).where(NewsArticle.ticker == ticker)).all()

            with Session(engine) as session:
                assert publish_batch(session, publisher, limit=50) >= 1

            sentiment = ConfluentBrokerConsumer(
                bootstrap_servers=_KAFKA, group_id=sentiment_group, topic=NEWS_TOPIC
            )
            try:
                payload = _poll_event(sentiment, EVENT_TYPE_NEWS_ARTICLE_INGESTED, ticker=ticker)
            finally:
                sentiment.close()

            ingested = parse_news_article_ingested(payload)
            with Session(engine) as session:
                persist_article_sentiment(
                    session,
                    ingested,
                    SentimentScore(
                        label="positive", score=0.81, model="kafka-fake", confidence=0.9
                    ),
                )
                session.commit()
                assert session.exec(select(NewsSentiment)).all()

            with Session(engine) as session:
                assert publish_batch(session, publisher, limit=50) >= 1

            agg = ConfluentBrokerConsumer(
                bootstrap_servers=_KAFKA, group_id=agg_group, topic=NEWS_TOPIC
            )
            try:
                payload = _poll_event(agg, EVENT_TYPE_NEWS_SENTIMENT_SCORED, ticker=ticker)
            finally:
                agg.close()

            with Session(engine) as session:
                apply_news_sentiment_scored(session, parse_news_sentiment_scored(payload))
                session.commit()
                metrics = session.get(SymbolMetrics, ticker)
                assert metrics is not None
                assert metrics.sentiment_7d is not None
                assert metrics.sentiment_article_count >= 1
        finally:
            publisher.close()
