"""`/v1/symbols/{ticker}/indicators` — technical indicators on demand.

Accepts a comma-separated ``names`` list (``sma_20,sma_50,rsi_14,macd``).
The router fetches the bar series once, runs each requested indicator, and
returns a single bundle so the chart only has to make one round-trip.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from stockviz.db import get_session
from stockviz.models import PriceBar, Symbol
from stockviz.schemas import (
    IndicatorPointOut,
    IndicatorsOut,
    MACDPointOut,
)
from stockviz.services.indicators import (
    compute_ema,
    compute_macd,
    compute_rsi,
    compute_sma,
)

router = APIRouter(prefix="/v1/symbols", tags=["indicators"])

SessionDep = Annotated[Session, Depends(get_session)]

MAX_BARS = 5000
"""Hard cap on the bar window we'll feed indicators. Matches the bars router."""

ALLOWED = {"sma", "ema", "rsi", "macd"}
_PERIODIC = re.compile(r"^(sma|ema|rsi)_(\d{1,3})$")


def _parse_names(raw: str) -> list[tuple[str, int | None]]:
    """``"sma_20,macd,rsi_14"`` -> ``[("sma", 20), ("macd", None), ("rsi", 14)]``."""
    parsed: list[tuple[str, int | None]] = []
    for chunk in raw.split(","):
        name = chunk.strip().lower()
        if not name:
            continue
        if name == "macd":
            parsed.append(("macd", None))
            continue
        match = _PERIODIC.match(name)
        if not match:
            raise HTTPException(status_code=400, detail=f"Unknown indicator: {name!r}")
        kind, period_str = match.groups()
        if kind not in ALLOWED:
            raise HTTPException(status_code=400, detail=f"Unknown indicator: {kind!r}")
        period = int(period_str)
        if period <= 0 or period > 500:
            raise HTTPException(status_code=400, detail=f"Indicator period out of range: {period}")
        parsed.append((kind, period))
    if not parsed:
        raise HTTPException(status_code=400, detail="At least one indicator name is required")
    return parsed


@router.get("/{ticker}/indicators", response_model=IndicatorsOut)
def get_indicators(
    ticker: str,
    session: SessionDep,
    names: Annotated[str, Query(description="e.g. sma_20,sma_50,rsi_14,macd")],
    interval: Annotated[str, Query(pattern=r"^(1d|1h)$")] = "1d",
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_BARS)] = 1000,
) -> IndicatorsOut:
    ticker = ticker.upper()
    if session.get(Symbol, ticker) is None:
        raise HTTPException(status_code=404, detail=f"Symbol {ticker!r} not found")

    parsed = _parse_names(names)

    stmt = select(PriceBar).where(PriceBar.ticker == ticker, PriceBar.interval == interval)
    if from_ is not None:
        stmt = stmt.where(PriceBar.ts >= from_)
    if to is not None:
        stmt = stmt.where(PriceBar.ts <= to)
    stmt = stmt.order_by(PriceBar.ts.desc()).limit(limit)  # type: ignore[attr-defined]
    rows = list(session.exec(stmt).all())
    rows.reverse()

    bars = [(r.ts, r.close) for r in rows]

    series: dict[str, list[IndicatorPointOut]] = {}
    macd_points: list[MACDPointOut] | None = None

    for kind, period in parsed:
        if kind == "macd":
            macd_points = [
                MACDPointOut(ts=p.ts, macd=p.macd, signal=p.signal, histogram=p.histogram)
                for p in compute_macd(bars)
            ]
            continue
        assert period is not None  # _parse_names guarantees this
        if kind == "sma":
            pts = compute_sma(bars, period=period)
            key = f"sma_{period}"
        elif kind == "ema":
            pts = compute_ema(bars, period=period)
            key = f"ema_{period}"
        else:  # rsi
            pts = compute_rsi(bars, period=period)
            key = f"rsi_{period}"
        series[key] = [IndicatorPointOut(ts=p.ts, value=p.value) for p in pts]

    return IndicatorsOut(ticker=ticker, series=series, macd=macd_points)
