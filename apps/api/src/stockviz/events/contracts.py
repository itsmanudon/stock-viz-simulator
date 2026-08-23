"""Versioned Kafka event contracts.

Decimals travel as strings so JSON cannot round-trip them through binary
floats. ORM models are never placed on the wire.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

EVENT_TYPE_TRADE_EXECUTED = "trade.executed"
SCHEMA_VERSION_V1 = 1
TRADES_TOPIC = "stockviz.trades.v1"
TRADE_ACTIVITY_CONSUMER = "stockviz.trade-activity.v1"

# Three partitions: enough for local fan-out by portfolio_id without pretending
# this workload needs a large cluster. Keys are portfolio_id so one book stays
# ordered on one partition.
TRADES_TOPIC_PARTITIONS = 3


def decimal_str(value: Decimal) -> str:
    """Canonical non-scientific decimal string."""
    return format(value, "f")


class TradeExecutedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trade_id: int
    portfolio_id: int
    ticker: str
    side: Literal["buy", "sell"]
    quantity: str
    price: str
    currency: str
    fx_rate: str
    usd_notional: str

    @field_validator("quantity", "price", "fx_rate", "usd_notional")
    @classmethod
    def _reject_blank_decimal(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("decimal fields must be non-empty strings")
        Decimal(text)
        return text


class TradeExecutedEvent(BaseModel):
    """Envelope stored in the outbox and published as the Kafka value."""

    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    event_type: Literal["trade.executed"] = EVENT_TYPE_TRADE_EXECUTED
    schema_version: Literal[1] = SCHEMA_VERSION_V1
    occurred_at: datetime
    aggregate_type: Literal["portfolio"] = "portfolio"
    aggregate_id: str
    payload: TradeExecutedPayload

    @field_validator("aggregate_id")
    @classmethod
    def _aggregate_matches_portfolio(cls, value: str) -> str:
        if not value:
            raise ValueError("aggregate_id is required")
        return value
