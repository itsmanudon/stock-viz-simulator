"""Tests for GET /v1/stream/quotes/{ticker} (SSE).

We call the endpoint function directly (bypassing TestClient) so we can
iterate the async generator and break after the first event without the
infinite stream hanging the test suite.
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal

import pytest
from sqlmodel import Session

from stockviz.models import PriceBar
from stockviz.routers.stream import stream_quotes


def _add_bar(session: Session, ticker: str, close: Decimal) -> None:
    session.add(
        PriceBar(
            ticker=ticker,
            ts=datetime(2024, 1, 2),
            interval="1d",
            open=close,
            high=close,
            low=close,
            close=close,
            volume=1_000_000,
        )
    )
    session.commit()


async def _first_event(ticker: str, session: Session) -> dict:
    """Call stream_quotes directly and return the first SSE payload."""
    response = await stream_quotes(ticker, session)
    async for chunk in response.body_iterator:  # type: ignore[union-attr]
        line = (chunk.decode() if isinstance(chunk, bytes) else str(chunk)).strip()
        if line.startswith("data:"):
            return json.loads(line[len("data:") :].strip())
    return {}


@pytest.mark.asyncio
async def test_stream_returns_event_stream_media_type(session: Session) -> None:
    _add_bar(session, "AAPL", Decimal("150.00"))
    response = await stream_quotes("AAPL", session)
    assert response.media_type == "text/event-stream"
    assert response.headers["cache-control"] == "no-cache"


@pytest.mark.asyncio
async def test_stream_emits_price_for_known_ticker(session: Session) -> None:
    _add_bar(session, "MSFT", Decimal("300.50"))
    event = await _first_event("MSFT", session)
    assert event.get("ticker") == "MSFT"
    assert isinstance(event.get("price"), (int, float))
    assert event["price"] > 0


@pytest.mark.asyncio
async def test_stream_normalises_ticker_to_uppercase(session: Session) -> None:
    _add_bar(session, "GOOGL", Decimal("175.00"))
    event = await _first_event("googl", session)
    assert event.get("ticker") == "GOOGL"


@pytest.mark.asyncio
async def test_stream_error_event_for_unknown_ticker(session: Session) -> None:
    event = await _first_event("FAKE", session)
    assert "error" in event


@pytest.mark.asyncio
async def test_stream_initial_price_matches_last_close(session: Session) -> None:
    _add_bar(session, "TSLA", Decimal("200.00"))
    event = await _first_event("TSLA", session)
    # First tick is the last close before the random walk starts
    assert event["price"] == 200.00
