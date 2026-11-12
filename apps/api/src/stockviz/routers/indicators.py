"""`/v1/symbols/{ticker}/indicators` — technical indicators on demand.

Accepts a comma-separated ``names`` list (``sma_20,rsi_14,macd,bb_20_2``):
any indicator in ``services/indicators/engine.REGISTRY`` with its parameters
joined by ``_`` (defaults when omitted). ``/v1/indicators/catalog`` lists them.
The router fetches the bar series once, runs each requested indicator, and
returns a single bundle so the chart only has to make one round-trip.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlmodel import Session, select

from stockviz.db import get_session
from stockviz.limiter import limiter
from stockviz.models import PriceBar, Symbol
from stockviz.schemas import IndicatorCatalogItemOut, IndicatorsOut
from stockviz.services.indicator_view import compute_bundle
from stockviz.services.indicators import engine
from stockviz.services.instruments import instrument_of

router = APIRouter(prefix="/v1/symbols", tags=["indicators"])
catalog_router = APIRouter(prefix="/v1/indicators", tags=["indicators"])

SessionDep = Annotated[Session, Depends(get_session)]

MAX_BARS = 5000
"""Hard cap on the bar window we'll feed indicators. Matches the bars router."""

MAX_WARMUP = 5000
"""Cap on extra bars loaded before the window (the largest lookback is ADX at
20 x n; a 500-period ADX is not a request worth serving)."""


def _parse_names(raw: str) -> list[engine.Request]:
    """``"sma_20,macd,bb_20_2"`` -> engine requests (Phase 6.1 registry)."""
    parsed: list[engine.Request] = []
    for chunk in raw.split(","):
        if not chunk.strip():
            continue
        try:
            parsed.append(engine.parse(chunk))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not parsed:
        raise HTTPException(status_code=400, detail="At least one indicator name is required")
    if max(r.lookback for r in parsed) > MAX_WARMUP:
        raise HTTPException(status_code=400, detail="Indicator lookback too long")
    return parsed


@catalog_router.get("/catalog", response_model=list[IndicatorCatalogItemOut])
@limiter.limit("60/minute")
def get_catalog(request: Request) -> list[IndicatorCatalogItemOut]:
    """Every indicator the engine offers, with its parameters and defaults."""
    return [
        IndicatorCatalogItemOut(
            key=s.key,
            label=s.label,
            params=list(s.params),
            defaults=[float(d) for d in s.defaults],
            outputs=list(s.outputs),
            pane=s.pane,
            group=s.group,
        )
        for s in engine.REGISTRY.values()
    ]


@router.get("/{ticker}/indicators", response_model=IndicatorsOut)
@limiter.limit("60/minute")
def get_indicators(
    request: Request,
    ticker: str,
    session: SessionDep,
    names: Annotated[str, Query(description="e.g. sma_20,rsi_14,macd,bb_20_2")],
    interval: Annotated[str, Query(pattern=r"^(1d|1h)$")] = "1d",
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_BARS)] = 1000,
) -> IndicatorsOut:
    """Indicators over a window of bars, warmed up on the bars before it (RS-1).

    The window is the last ``limit`` bars within ``from``/``to``. The bars each
    indicator needs before that window are loaded too, so a value on a given
    day is the same whatever window the chart asks for.
    """
    ticker = ticker.upper()
    if session.get(Symbol, ticker) is None:
        raise HTTPException(status_code=404, detail=f"Symbol {ticker!r} not found")

    parsed = _parse_names(names)

    stmt = select(PriceBar).where(
        PriceBar.instrument_id == instrument_of(ticker), PriceBar.interval == interval
    )
    if from_ is not None:
        stmt = stmt.where(PriceBar.ts >= from_)
    if to is not None:
        stmt = stmt.where(PriceBar.ts <= to)
    stmt = stmt.order_by(PriceBar.ts.desc()).limit(limit)  # type: ignore[attr-defined]
    rows = list(session.exec(stmt).all())
    rows.reverse()

    window_start = rows[0].ts if rows else None
    warmup: list[PriceBar] = []
    lookback = max(r.lookback for r in parsed)
    if rows and lookback > 0:
        warmup = list(
            session.exec(
                select(PriceBar)
                .where(
                    PriceBar.instrument_id == instrument_of(ticker),
                    PriceBar.interval == interval,
                    PriceBar.ts < rows[0].ts,
                )
                .order_by(PriceBar.ts.desc())  # type: ignore[attr-defined]
                .limit(lookback)
            ).all()
        )
        warmup.reverse()

    ohlcv = [(r.ts, r.open, r.high, r.low, r.close, r.volume) for r in warmup + rows]
    return compute_bundle(
        ticker,
        interval,
        parsed,
        ohlcv,
        window_start=window_start,
        warmup_bars=len(warmup),
    )
