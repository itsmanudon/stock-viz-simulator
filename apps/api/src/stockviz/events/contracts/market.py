"""Market-data events on ``stockviz.market.v1``, keyed by ticker."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

from stockviz.events.contracts.common import SCHEMA_VERSION_V1

EVENT_TYPE_MARKET_REFRESH_REQUESTED = "market.refresh.requested"
EVENT_TYPE_MARKET_BARS_REFRESHED = "market.bars.refreshed"
MARKET_TOPIC = "stockviz.market.v1"
MARKET_TOPIC_PARTITIONS = 3
MARKET_INGEST_CONSUMER = "stockviz.market-ingestion.v1"
MARKET_ANALYTICS_CONSUMER = "stockviz.market-analytics.v1"

MarketRefreshReason = Literal["daily", "hourly", "manual"]


class MarketRefreshRequestedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str
    reason: MarketRefreshReason
    requested_at: datetime
    since: datetime | None = None

    @field_validator("ticker")
    @classmethod
    def _ticker_required(cls, value: str) -> str:
        text = value.strip().upper()
        if not text:
            raise ValueError("ticker is required")
        return text


class MarketRefreshRequestedEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    event_type: Literal["market.refresh.requested"] = EVENT_TYPE_MARKET_REFRESH_REQUESTED
    schema_version: Literal[1] = SCHEMA_VERSION_V1
    occurred_at: datetime
    aggregate_type: Literal["symbol"] = "symbol"
    aggregate_id: str
    payload: MarketRefreshRequestedPayload

    @field_validator("aggregate_id")
    @classmethod
    def _aggregate_required(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("aggregate_id is required")
        return value


class MarketBarsRefreshedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str
    interval: str
    source: str
    bar_count: int
    latest_bar_at: datetime | None = None
    latest_close: str | None = None
    request_event_id: str

    @field_validator("ticker")
    @classmethod
    def _ticker_required(cls, value: str) -> str:
        text = value.strip().upper()
        if not text:
            raise ValueError("ticker is required")
        return text

    @field_validator("latest_close")
    @classmethod
    def _close_decimal(cls, value: str | None) -> str | None:
        if value is None:
            return value
        text = value.strip()
        if not text:
            raise ValueError("latest_close must be a non-empty decimal string")
        Decimal(text)
        return text

    @field_validator("bar_count")
    @classmethod
    def _bar_count_non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("bar_count must be >= 0")
        return value


class MarketBarsRefreshedEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    event_type: Literal["market.bars.refreshed"] = EVENT_TYPE_MARKET_BARS_REFRESHED
    schema_version: Literal[1] = SCHEMA_VERSION_V1
    occurred_at: datetime
    aggregate_type: Literal["symbol"] = "symbol"
    aggregate_id: str
    payload: MarketBarsRefreshedPayload

    @field_validator("aggregate_id")
    @classmethod
    def _aggregate_required(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("aggregate_id is required")
        return value
