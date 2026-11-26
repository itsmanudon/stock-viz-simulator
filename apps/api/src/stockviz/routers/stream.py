"""`/v1/stream/bars`: closed intraday minute bars as server-sent events (A6.5).

``GET /v1/stream/bars?tickers=TCS,AAPL`` holds the response open and sends one
``bar`` event per minute bar the stream worker stores for those tickers (JSON:
ticker, feed, badge, ``ts`` = the bar's open, ``closed_at``, OHLCV as strings,
``replayed``), and a comment every :data:`HEARTBEAT_SECONDS` so proxies keep
it open. The events come from the worker's ``NOTIFY intraday_bar`` through
``services/stream/hub.py``; only stored bars are sent. Public like the bars
themselves; at most :data:`MAX_TICKERS` tickers a connection. The chart opens
it only on an intraday interval, so production (no intraday bars) opens none.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from stockviz.limiter import limiter
from stockviz.services.stream.hub import BarHub, HubFull, get_hub, sse

router = APIRouter(prefix="/v1/stream", tags=["stream"])

MAX_TICKERS = 10
HEARTBEAT_SECONDS = 15.0


def parse_tickers(raw: str) -> list[str]:
    tickers = sorted({t.strip().upper() for t in raw.split(",") if t.strip()})
    if not tickers:
        raise HTTPException(status_code=422, detail="name at least one ticker")
    if len(tickers) > MAX_TICKERS:
        raise HTTPException(status_code=422, detail=f"at most {MAX_TICKERS} tickers")
    if any(len(t) > 16 for t in tickers):
        raise HTTPException(status_code=422, detail="a ticker is at most 16 characters")
    return tickers


async def events(
    request: Request, hub: BarHub, tickers: list[str], *, heartbeat: float = HEARTBEAT_SECONDS
) -> AsyncIterator[str]:
    try:
        sub = hub.subscribe(tickers)
    except HubFull:
        yield "event: busy\ndata: {}\n\n"
        return
    try:
        yield ": connected\n\n"
        while True:
            try:
                event = await asyncio.wait_for(sub.queue.get(), timeout=heartbeat)
            except TimeoutError:
                if await request.is_disconnected():
                    return
                yield ": keep-alive\n\n"
                continue
            yield sse(event)
    finally:
        hub.unsubscribe(sub)


@router.get("/bars")
@limiter.limit("30/minute")
async def stream_bars(
    request: Request, tickers: Annotated[str, Query(max_length=200)]
) -> StreamingResponse:
    names = parse_tickers(tickers)
    return StreamingResponse(
        events(request, get_hub(), names),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
