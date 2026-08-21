"""Tests for GET /v1/stream/quotes/{ticker} (SSE).

We call the endpoint function directly (bypassing TestClient) so we can
iterate the async generator and break after the first event without the
stream hanging the test suite.

The endpoint takes the initial close as a resolved dependency rather than a
session: FastAPI holds ``yield`` dependencies open for the life of the
response, so a session-per-stream would pin one Postgres connection per
connected viewer. ``initial_close`` opens and closes its own session before
streaming starts.
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal

import pytest
from sqlmodel import Session

from stockviz.models import PriceBar
from stockviz.routers.stream import initial_close, stream_quotes


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


class _FakeRequest:
    """Minimal stand-in — the endpoint only awaits ``is_disconnected``."""

    async def is_disconnected(self) -> bool:
        return False


async def _stream(ticker: str, initial: float | None):
    return await stream_quotes(_FakeRequest(), ticker, initial)  # type: ignore[arg-type]


async def _first_event(ticker: str, initial: float | None) -> dict:
    """Call stream_quotes directly and return the first SSE payload."""
    response = await _stream(ticker, initial)
    async for chunk in response.body_iterator:  # type: ignore[union-attr]
        line = (chunk.decode() if isinstance(chunk, bytes) else str(chunk)).strip()
        if line.startswith("data:"):
            return json.loads(line[len("data:") :].strip())
    return {}


@pytest.mark.asyncio
async def test_stream_returns_event_stream_media_type(session: Session) -> None:
    _add_bar(session, "AAPL", Decimal("150.00"))
    response = await _stream("AAPL", 150.00)
    assert response.media_type == "text/event-stream"
    assert response.headers["cache-control"] == "no-cache"


@pytest.mark.asyncio
async def test_stream_emits_price_for_known_ticker(session: Session) -> None:
    _add_bar(session, "MSFT", Decimal("300.50"))
    event = await _first_event("MSFT", 300.50)
    assert event.get("ticker") == "MSFT"
    assert isinstance(event.get("price"), (int, float))
    assert event["price"] > 0


@pytest.mark.asyncio
async def test_stream_normalises_ticker_to_uppercase(session: Session) -> None:
    _add_bar(session, "GOOGL", Decimal("175.00"))
    event = await _first_event("googl", 175.00)
    assert event.get("ticker") == "GOOGL"


@pytest.mark.asyncio
async def test_stream_error_event_for_unknown_ticker(session: Session) -> None:
    event = await _first_event("FAKE", None)
    assert "error" in event


@pytest.mark.asyncio
async def test_stream_initial_price_matches_last_close(session: Session) -> None:
    _add_bar(session, "TSLA", Decimal("200.00"))
    event = await _first_event("TSLA", 200.00)
    # First tick is the last close before the random walk starts
    assert event["price"] == 200.00


def test_stream_route_does_not_depend_on_a_request_session() -> None:
    """Regression: a ``yield`` session dependency here pins one Postgres
    connection per connected viewer for the whole life of the stream, so a
    handful of open ticker pages exhausts the pool and deadlocks the API.

    ``initial_close`` opens and closes its own session instead.
    """
    from fastapi.dependencies.utils import get_dependant

    from stockviz.db import get_session

    # Inspect the endpoint's own dependency graph rather than walking
    # app.routes: Starlette nests included routers, and that structure has
    # already changed once across a minor version.
    dependant = get_dependant(path="/v1/stream/quotes/{ticker}", call=stream_quotes)
    dependency_calls = {d.call for d in dependant.dependencies}
    assert get_session not in dependency_calls
    assert initial_close in dependency_calls
