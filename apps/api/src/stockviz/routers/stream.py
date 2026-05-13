"""`GET /v1/stream/quotes/{ticker}` — simulated live SSE price ticker.

Since StockViz stores EOD prices (not real-time data), the stream starts
from the latest close and applies a small Gaussian random walk to simulate
live price movement. This is clearly a simulation; the ticker detail page
labels it accordingly.

The session dependency is resolved once at connect time (to fetch the
initial close) and the generator then runs autonomously, yielding a price
event every ~3 seconds until the client disconnects.
"""

from __future__ import annotations

import asyncio
import json
import math
import random
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from stockviz.db import get_session
from stockviz.models import PriceBar

router = APIRouter(prefix="/v1/stream", tags=["stream"])

SessionDep = Annotated[Session, Depends(get_session)]

_POLL_SECONDS = 3
_VOLATILITY = 0.001  # per-tick Gaussian std dev (≈ 0.1%)


@router.get("/quotes/{ticker}")
async def stream_quotes(ticker: str, session: SessionDep) -> StreamingResponse:
    """SSE: simulated live price, updated every ~3 s."""
    t = ticker.strip().upper()
    bar = session.exec(
        select(PriceBar)
        .where(
            PriceBar.ticker == t,  # pyright: ignore[reportArgumentType]
            PriceBar.interval == "1d",  # pyright: ignore[reportArgumentType]
        )
        .order_by(PriceBar.ts.desc())  # type: ignore[attr-defined]
        .limit(1)
    ).first()
    initial = float(bar.close) if bar is not None else None

    async def _events() -> AsyncGenerator[str, None]:
        if initial is None:
            yield f"data: {json.dumps({'error': 'no price data'})}\n\n"
            return
        price = initial
        while True:
            yield f"data: {json.dumps({'ticker': t, 'price': round(price, 2)})}\n\n"
            await asyncio.sleep(_POLL_SECONDS)
            price = max(0.01, price * math.exp(random.gauss(0, _VOLATILITY)))

    return StreamingResponse(
        _events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
