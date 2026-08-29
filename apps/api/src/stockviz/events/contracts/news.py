"""News events on ``stockviz.news.v1``, keyed by ticker."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

from stockviz.events.contracts.common import SCHEMA_VERSION_V1

EVENT_TYPE_NEWS_REFRESH_REQUESTED = "news.refresh.requested"
EVENT_TYPE_NEWS_ARTICLE_INGESTED = "news.article.ingested"
EVENT_TYPE_NEWS_SENTIMENT_SCORED = "news.sentiment.scored"
NEWS_TOPIC = "stockviz.news.v1"
NEWS_TOPIC_PARTITIONS = 3
NEWS_INGEST_CONSUMER = "stockviz.news-ingestion.v1"
NEWS_SENTIMENT_CONSUMER = "stockviz.news-sentiment.v1"
SENTIMENT_AGGREGATE_CONSUMER = "stockviz.sentiment-aggregate.v1"

NewsRefreshReason = Literal["scheduled", "manual"]


class NewsRefreshRequestedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str
    company_name: str
    reason: NewsRefreshReason
    requested_at: datetime

    @field_validator("ticker")
    @classmethod
    def _ticker_required(cls, value: str) -> str:
        text = value.strip().upper()
        if not text:
            raise ValueError("ticker is required")
        return text

    @field_validator("company_name")
    @classmethod
    def _company_required(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("company_name is required")
        return text


class NewsRefreshRequestedEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    event_type: Literal["news.refresh.requested"] = EVENT_TYPE_NEWS_REFRESH_REQUESTED
    schema_version: Literal[1] = SCHEMA_VERSION_V1
    occurred_at: datetime
    aggregate_type: Literal["symbol"] = "symbol"
    aggregate_id: str
    payload: NewsRefreshRequestedPayload

    @field_validator("aggregate_id")
    @classmethod
    def _aggregate_required(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("aggregate_id is required")
        return value


class NewsArticleIngestedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    article_id: int
    ticker: str
    url: str
    published_at: datetime
    source: str | None = None

    @field_validator("ticker")
    @classmethod
    def _ticker_required(cls, value: str) -> str:
        text = value.strip().upper()
        if not text:
            raise ValueError("ticker is required")
        return text

    @field_validator("url")
    @classmethod
    def _url_required(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("url is required")
        return text


class NewsArticleIngestedEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    event_type: Literal["news.article.ingested"] = EVENT_TYPE_NEWS_ARTICLE_INGESTED
    schema_version: Literal[1] = SCHEMA_VERSION_V1
    occurred_at: datetime
    aggregate_type: Literal["symbol"] = "symbol"
    aggregate_id: str
    payload: NewsArticleIngestedPayload

    @field_validator("aggregate_id")
    @classmethod
    def _aggregate_required(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("aggregate_id is required")
        return value


class NewsSentimentScoredPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    article_id: int
    ticker: str
    model: str
    label: str
    score: str
    confidence: str | None = None

    @field_validator("ticker")
    @classmethod
    def _ticker_required(cls, value: str) -> str:
        text = value.strip().upper()
        if not text:
            raise ValueError("ticker is required")
        return text

    @field_validator("score", "confidence")
    @classmethod
    def _decimal_fields(cls, value: str | None) -> str | None:
        if value is None:
            return value
        text = value.strip()
        if not text:
            raise ValueError("decimal fields must be non-empty strings")
        Decimal(text)
        return text


class NewsSentimentScoredEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    event_type: Literal["news.sentiment.scored"] = EVENT_TYPE_NEWS_SENTIMENT_SCORED
    schema_version: Literal[1] = SCHEMA_VERSION_V1
    occurred_at: datetime
    aggregate_type: Literal["symbol"] = "symbol"
    aggregate_id: str
    payload: NewsSentimentScoredPayload

    @field_validator("aggregate_id")
    @classmethod
    def _aggregate_required(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("aggregate_id is required")
        return value
