"""`/v1/symbols/screen` — filter the symbol universe by technical criteria.

Combines static metadata (sector) with computed metrics from the ``bars``
table (RSI, N-day momentum, 52-week range proximity). All filters are AND'd
together — a symbol must satisfy every supplied predicate to appear.

For each symbol the latest 252 daily bars (~one trading year) are pulled
once and reused for every metric. Symbols without enough history to
evaluate a requested metric are dropped silently.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlmodel import Session, select

from stockviz.db import get_session
from stockviz.limiter import limiter
from stockviz.models import PriceBar, Symbol
from stockviz.schemas import ScreenerResultOut
from stockviz.services.indicators import compute_rsi

router = APIRouter(prefix="/v1/symbols", tags=["screener"])

SessionDep = Annotated[Session, Depends(get_session)]

# One trading year is enough for every supported metric — RSI(14), N-day
# momentum (capped at ``MAX_MOMENTUM_DAYS``), and the 52-week window.
LOOKBACK_BARS = 260
MAX_MOMENTUM_DAYS = 252
NEAR_52W_THRESHOLD = Decimal("0.05")
"""How close to the 52-week extreme we count as ``near``. 5% by default."""


@dataclass
class _Computed:
    last_close: Decimal
    rsi: float | None
    momentum_pct: float | None
    high_52w: Decimal
    low_52w: Decimal


def _compute(bars: list[PriceBar], *, momentum_days: int | None) -> _Computed | None:
    if not bars:
        return None
    closes = [(b.ts, b.close) for b in bars]
    last_close = bars[-1].close

    rsi_points = compute_rsi(closes, period=14)
    rsi = rsi_points[-1].value if rsi_points else None

    momentum_pct: float | None = None
    if momentum_days is not None and len(bars) > momentum_days:
        prior_close = bars[-1 - momentum_days].close
        if prior_close != 0:
            momentum_pct = float((last_close - prior_close) / prior_close * 100)

    closes_only = [b.close for b in bars]
    return _Computed(
        last_close=last_close,
        rsi=rsi,
        momentum_pct=momentum_pct,
        high_52w=max(closes_only),
        low_52w=min(closes_only),
    )


@router.get("/screen", response_model=list[ScreenerResultOut])
@limiter.limit("30/minute")
def screen_symbols(
    request: Request,
    session: SessionDep,
    sector: Annotated[str | None, Query()] = None,
    rsi_min: Annotated[float | None, Query(ge=0, le=100)] = None,
    rsi_max: Annotated[float | None, Query(ge=0, le=100)] = None,
    momentum_days: Annotated[int | None, Query(ge=1, le=MAX_MOMENTUM_DAYS)] = None,
    momentum_min: Annotated[float | None, Query()] = None,
    momentum_max: Annotated[float | None, Query()] = None,
    near_52w_high: Annotated[bool, Query()] = False,
    near_52w_low: Annotated[bool, Query()] = False,
) -> list[ScreenerResultOut]:
    sym_stmt = select(Symbol).where(Symbol.is_active)
    if sector is not None:
        sym_stmt = sym_stmt.where(Symbol.sector == sector)
    symbols = list(session.exec(sym_stmt).all())

    results: list[ScreenerResultOut] = []
    for symbol in symbols:
        bar_stmt = (
            select(PriceBar)
            .where(PriceBar.ticker == symbol.ticker, PriceBar.interval == "1d")
            .order_by(PriceBar.ts.desc())  # type: ignore[attr-defined]
            .limit(LOOKBACK_BARS)
        )
        bars = list(session.exec(bar_stmt).all())
        bars.reverse()

        metrics = _compute(bars, momentum_days=momentum_days)
        if metrics is None:
            continue

        if rsi_min is not None and (metrics.rsi is None or metrics.rsi < rsi_min):
            continue
        if rsi_max is not None and (metrics.rsi is None or metrics.rsi > rsi_max):
            continue

        if momentum_days is not None:
            if metrics.momentum_pct is None:
                continue
            if momentum_min is not None and metrics.momentum_pct < momentum_min:
                continue
            if momentum_max is not None and metrics.momentum_pct > momentum_max:
                continue

        if near_52w_high:
            band = metrics.high_52w * (Decimal(1) - NEAR_52W_THRESHOLD)
            if metrics.last_close < band:
                continue
        if near_52w_low:
            band = metrics.low_52w * (Decimal(1) + NEAR_52W_THRESHOLD)
            if metrics.last_close > band:
                continue

        results.append(
            ScreenerResultOut(
                ticker=symbol.ticker,
                name=symbol.name,
                sector=symbol.sector,
                exchange=symbol.exchange,
                currency=symbol.currency,
                last_close=metrics.last_close,
                rsi_14=metrics.rsi,
                momentum_pct=metrics.momentum_pct,
                momentum_days=momentum_days,
                high_52w=metrics.high_52w,
                low_52w=metrics.low_52w,
            )
        )

    results.sort(key=lambda r: r.ticker)
    return results
