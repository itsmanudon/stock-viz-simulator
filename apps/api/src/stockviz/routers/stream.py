"""`GET /v1/stream/quotes/{ticker}` — simulated live SSE price ticker.

Since StockViz stores EOD prices (not real-time data), the stream starts
from the latest close and applies a small Gaussian random walk to simulate
live price movement. This is clearly a simulation; the ticker detail page
labels it accordingly.

**Connection handling.** The initial close is read inside an explicit session
that closes before the response starts. This endpoint deliberately does *not*
take the ``get_session`` dependency: FastAPI holds ``yield`` dependencies open
for the lifetime of the response, so with a long-lived ``StreamingResponse``
every connected client would pin one Postgres connection. The default pool is
5 + 10 overflow, so roughly fifteen viewers of a ticker page would have
deadlocked the whole API.

Streams also stop themselves after ``MAX_STREAM_SECONDS`` rather than running
forever, and are rate-limited per IP like the other public reads.
"""

from __future__ import annotations

import asyncio
import json
import math
import random
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from stockviz.db import engine
from stockviz.limiter import limiter
from stockviz.models import PriceBar

router = APIRouter(prefix="/v1/stream", tags=["stream"])

_POLL_SECONDS = 3
_VOLATILITY = 0.001  # per-tick Gaussian std dev (≈ 0.1%)

MAX_STREAM_SECONDS = 15 * 60
"""Hard cap on a single connection. Clients reconnect; EventSource does so
automatically. Without this a forgotten browser tab holds a worker slot
indefinitely."""

_MAX_TICKS = MAX_STREAM_SECONDS // _POLL_SECONDS


def initial_close(ticker: str) -> float | None:
    """Latest 1d close for ``ticker``, read and released before streaming starts.

    Deliberately a plain function rather than a ``yield`` dependency: FastAPI
    keeps generator dependencies open for the whole response, which for a
    long-lived stream would pin a connection per viewer. The ``with`` block
    returns the connection to the pool before this returns. Tests and other
    callers can still override it via ``app.dependency_overrides``.
    """
    t = ticker.strip().upper()
    with Session(engine) as session:
        bar = session.exec(
            select(PriceBar)
            .where(
                PriceBar.ticker == t,  # pyright: ignore[reportArgumentType]
                PriceBar.interval == "1d",  # pyright: ignore[reportArgumentType]
            )
            .order_by(PriceBar.ts.desc())  # type: ignore[attr-defined]
            .limit(1)
        ).first()
        return float(bar.close) if bar is not None else None


InitialCloseDep = Annotated[float | None, Depends(initial_close)]


@router.get("/quotes/{ticker}")
@limiter.limit("10/minute")
async def stream_quotes(
    request: Request, ticker: str, initial: InitialCloseDep
) -> StreamingResponse:
    """SSE: simulated live price, updated every ~3 s, capped at 15 minutes."""
    t = ticker.strip().upper()

    async def _events() -> AsyncGenerator[str, None]:
        if initial is None:
            yield f"data: {json.dumps({'error': 'no price data'})}\n\n"
            return
        price = initial
        for _ in range(_MAX_TICKS):
            if await request.is_disconnected():
                return
            yield f"data: {json.dumps({'ticker': t, 'price': round(price, 2)})}\n\n"
            await asyncio.sleep(_POLL_SECONDS)
            price = max(0.01, price * math.exp(random.gauss(0, _VOLATILITY)))
        # Tell the client why we stopped so it can reconnect deliberately.
        yield f"event: timeout\ndata: {json.dumps({'reason': 'max duration reached'})}\n\n"

    return StreamingResponse(
        _events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
