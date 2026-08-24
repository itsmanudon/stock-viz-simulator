"""v1 market/news event contracts: envelope, payload, key, version rejection."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest

from stockviz.events.contracts import (
    EVENT_TYPE_MARKET_BARS_REFRESHED,
    EVENT_TYPE_MARKET_REFRESH_REQUESTED,
    EVENT_TYPE_NEWS_ARTICLE_INGESTED,
    EVENT_TYPE_NEWS_REFRESH_REQUESTED,
    EVENT_TYPE_NEWS_SENTIMENT_SCORED,
    MARKET_TOPIC,
    NEWS_TOPIC,
    SCHEMA_VERSION_V1,
    MarketBarsRefreshedEvent,
    MarketBarsRefreshedPayload,
    MarketRefreshRequestedEvent,
    MarketRefreshRequestedPayload,
    NewsArticleIngestedEvent,
    NewsArticleIngestedPayload,
    NewsRefreshRequestedEvent,
    NewsRefreshRequestedPayload,
    NewsSentimentScoredEvent,
    NewsSentimentScoredPayload,
)
from stockviz.events.outbox import (
    parse_market_bars_refreshed,
    parse_market_refresh_requested,
    parse_news_article_ingested,
    parse_news_refresh_requested,
    parse_news_sentiment_scored,
)

OCCURRED = datetime(2026, 4, 10, 20, 30, 0)


def _reject_bad_version(parse, event_type: str, payload: dict) -> None:
    envelope = {
        "event_id": str(uuid4()),
        "event_type": event_type,
        "schema_version": 99,
        "occurred_at": OCCURRED.isoformat(),
        "aggregate_type": "symbol",
        "aggregate_id": "AAPL",
        "payload": payload,
    }
    with pytest.raises(Exception, match="schema_version"):
        parse(envelope)


def test_market_refresh_requested_roundtrip() -> None:
    event = MarketRefreshRequestedEvent(
        event_id=uuid4(),
        occurred_at=OCCURRED,
        aggregate_id="AAPL",
        payload=MarketRefreshRequestedPayload(
            ticker="aapl",
            reason="daily",
            requested_at=OCCURRED,
            since=None,
        ),
    )
    raw = event.model_dump(mode="json")
    parsed = parse_market_refresh_requested(raw)
    assert parsed.event_type == EVENT_TYPE_MARKET_REFRESH_REQUESTED
    assert parsed.schema_version == SCHEMA_VERSION_V1
    assert parsed.payload.ticker == "AAPL"
    assert parsed.aggregate_id == "AAPL"
    assert MARKET_TOPIC == "stockviz.market.v1"


def test_market_bars_refreshed_roundtrip() -> None:
    request_id = uuid4()
    event = MarketBarsRefreshedEvent(
        event_id=uuid4(),
        occurred_at=OCCURRED,
        aggregate_id="MSFT",
        payload=MarketBarsRefreshedPayload(
            ticker="MSFT",
            interval="1d",
            source="yfinance",
            bar_count=20,
            latest_bar_at=OCCURRED,
            latest_close="182.4000",
            request_event_id=str(request_id),
        ),
    )
    parsed = parse_market_bars_refreshed(event.model_dump(mode="json"))
    assert parsed.event_type == EVENT_TYPE_MARKET_BARS_REFRESHED
    assert parsed.payload.latest_close == "182.4000"
    assert parsed.payload.request_event_id == str(request_id)


def test_news_refresh_requested_roundtrip() -> None:
    event = NewsRefreshRequestedEvent(
        event_id=uuid4(),
        occurred_at=OCCURRED,
        aggregate_id="AAPL",
        payload=NewsRefreshRequestedPayload(
            ticker="AAPL",
            company_name="Apple Inc.",
            reason="scheduled",
            requested_at=OCCURRED,
        ),
    )
    parsed = parse_news_refresh_requested(event.model_dump(mode="json"))
    assert parsed.event_type == EVENT_TYPE_NEWS_REFRESH_REQUESTED
    assert parsed.payload.company_name == "Apple Inc."
    assert NEWS_TOPIC == "stockviz.news.v1"


def test_news_article_ingested_roundtrip() -> None:
    event = NewsArticleIngestedEvent(
        event_id=uuid4(),
        occurred_at=OCCURRED,
        aggregate_id="AAPL",
        payload=NewsArticleIngestedPayload(
            article_id=42,
            ticker="AAPL",
            url="https://example.test/aapl-1",
            published_at=OCCURRED,
            source="reuters",
        ),
    )
    parsed = parse_news_article_ingested(event.model_dump(mode="json"))
    assert parsed.event_type == EVENT_TYPE_NEWS_ARTICLE_INGESTED
    assert parsed.payload.article_id == 42


def test_news_sentiment_scored_roundtrip() -> None:
    event = NewsSentimentScoredEvent(
        event_id=uuid4(),
        occurred_at=OCCURRED,
        aggregate_id="AAPL",
        payload=NewsSentimentScoredPayload(
            article_id=42,
            ticker="AAPL",
            model="fake-v1",
            label="positive",
            score="0.7421",
            confidence="0.9100",
        ),
    )
    parsed = parse_news_sentiment_scored(event.model_dump(mode="json"))
    assert parsed.event_type == EVENT_TYPE_NEWS_SENTIMENT_SCORED
    assert parsed.payload.score == "0.7421"


def test_unsupported_schema_versions_rejected() -> None:
    _reject_bad_version(
        parse_market_refresh_requested,
        EVENT_TYPE_MARKET_REFRESH_REQUESTED,
        {"ticker": "AAPL", "reason": "daily", "requested_at": OCCURRED.isoformat()},
    )
    _reject_bad_version(
        parse_market_bars_refreshed,
        EVENT_TYPE_MARKET_BARS_REFRESHED,
        {
            "ticker": "AAPL",
            "interval": "1d",
            "source": "yfinance",
            "bar_count": 1,
            "request_event_id": str(uuid4()),
        },
    )
    _reject_bad_version(
        parse_news_refresh_requested,
        EVENT_TYPE_NEWS_REFRESH_REQUESTED,
        {
            "ticker": "AAPL",
            "company_name": "Apple",
            "reason": "scheduled",
            "requested_at": OCCURRED.isoformat(),
        },
    )
    _reject_bad_version(
        parse_news_article_ingested,
        EVENT_TYPE_NEWS_ARTICLE_INGESTED,
        {
            "article_id": 1,
            "ticker": "AAPL",
            "url": "https://example.test/x",
            "published_at": OCCURRED.isoformat(),
        },
    )
    _reject_bad_version(
        parse_news_sentiment_scored,
        EVENT_TYPE_NEWS_SENTIMENT_SCORED,
        {
            "article_id": 1,
            "ticker": "AAPL",
            "model": "x",
            "label": "neutral",
            "score": "0",
        },
    )


def test_blank_ticker_rejected() -> None:
    with pytest.raises(Exception, match="ticker"):
        MarketRefreshRequestedPayload(
            ticker="  ",
            reason="manual",
            requested_at=OCCURRED,
        )
