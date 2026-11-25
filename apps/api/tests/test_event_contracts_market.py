"""v1 market event contracts: envelope, payload, key, version rejection."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest

from stockviz.events.contracts import (
    EVENT_TYPE_MARKET_BARS_REFRESHED,
    EVENT_TYPE_MARKET_REFRESH_REQUESTED,
    MARKET_TOPIC,
    SCHEMA_VERSION_V1,
    MarketBarsRefreshedEvent,
    MarketBarsRefreshedPayload,
    MarketRefreshRequestedEvent,
    MarketRefreshRequestedPayload,
)
from stockviz.events.outbox import (
    parse_market_bars_refreshed,
    parse_market_refresh_requested,
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


def test_blank_ticker_rejected() -> None:
    with pytest.raises(Exception, match="ticker"):
        MarketRefreshRequestedPayload(
            ticker="  ",
            reason="manual",
            requested_at=OCCURRED,
        )
