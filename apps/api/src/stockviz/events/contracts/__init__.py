"""Versioned Kafka event contracts.

Split by domain so ``trade.executed`` stays stable while market/news grow.
Decimals travel as strings. ORM models are never placed on the wire.
"""

from stockviz.events.contracts.common import SCHEMA_VERSION_V1, decimal_str
from stockviz.events.contracts.market import (
    EVENT_TYPE_MARKET_BARS_REFRESHED,
    EVENT_TYPE_MARKET_REFRESH_REQUESTED,
    MARKET_ANALYTICS_CONSUMER,
    MARKET_INGEST_CONSUMER,
    MARKET_TOPIC,
    MARKET_TOPIC_PARTITIONS,
    MarketBarsRefreshedEvent,
    MarketBarsRefreshedPayload,
    MarketRefreshRequestedEvent,
    MarketRefreshRequestedPayload,
)
from stockviz.events.contracts.news import (
    EVENT_TYPE_NEWS_ARTICLE_INGESTED,
    EVENT_TYPE_NEWS_REFRESH_REQUESTED,
    EVENT_TYPE_NEWS_SENTIMENT_SCORED,
    NEWS_INGEST_CONSUMER,
    NEWS_SENTIMENT_CONSUMER,
    NEWS_TOPIC,
    NEWS_TOPIC_PARTITIONS,
    SENTIMENT_AGGREGATE_CONSUMER,
    NewsArticleIngestedEvent,
    NewsArticleIngestedPayload,
    NewsRefreshRequestedEvent,
    NewsRefreshRequestedPayload,
    NewsSentimentScoredEvent,
    NewsSentimentScoredPayload,
)
from stockviz.events.contracts.trades import (
    EVENT_TYPE_TRADE_EXECUTED,
    TRADE_ACTIVITY_CONSUMER,
    TRADES_TOPIC,
    TRADES_TOPIC_PARTITIONS,
    TradeExecutedEvent,
    TradeExecutedPayload,
)

__all__ = [
    "EVENT_TYPE_MARKET_BARS_REFRESHED",
    "EVENT_TYPE_MARKET_REFRESH_REQUESTED",
    "EVENT_TYPE_NEWS_ARTICLE_INGESTED",
    "EVENT_TYPE_NEWS_REFRESH_REQUESTED",
    "EVENT_TYPE_NEWS_SENTIMENT_SCORED",
    "EVENT_TYPE_TRADE_EXECUTED",
    "MARKET_ANALYTICS_CONSUMER",
    "MARKET_INGEST_CONSUMER",
    "MARKET_TOPIC",
    "MARKET_TOPIC_PARTITIONS",
    "NEWS_INGEST_CONSUMER",
    "NEWS_SENTIMENT_CONSUMER",
    "NEWS_TOPIC",
    "NEWS_TOPIC_PARTITIONS",
    "SCHEMA_VERSION_V1",
    "SENTIMENT_AGGREGATE_CONSUMER",
    "TRADES_TOPIC",
    "TRADES_TOPIC_PARTITIONS",
    "TRADE_ACTIVITY_CONSUMER",
    "MarketBarsRefreshedEvent",
    "MarketBarsRefreshedPayload",
    "MarketRefreshRequestedEvent",
    "MarketRefreshRequestedPayload",
    "NewsArticleIngestedEvent",
    "NewsArticleIngestedPayload",
    "NewsRefreshRequestedEvent",
    "NewsRefreshRequestedPayload",
    "NewsSentimentScoredEvent",
    "NewsSentimentScoredPayload",
    "TradeExecutedEvent",
    "TradeExecutedPayload",
    "decimal_str",
]
