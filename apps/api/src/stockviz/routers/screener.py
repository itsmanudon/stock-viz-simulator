"""Screening the universe (Phase 6.2).

- ``GET /v1/screener``: the unified screener. Market (country), exchange
  (MIC) and currency filters for both markets, technical filters from the
  nightly snapshot, server-side sort and offset paging with a total.
- ``GET /v1/symbols/screen``: the original list endpoint, kept for its
  callers (screener-era pages, the landing page's proofs). Same query path,
  so momentum is now applied before the limit too (audit RS-5).

Filters read the precomputed ``symbol_metrics`` snapshot rather than
rescanning ``price_bars``; see ``services/screener.py``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlmodel import Session

from stockviz.db import get_session
from stockviz.limiter import limiter
from stockviz.schemas import ScreenerPageOut, ScreenerResultOut, ScreenerRowOut
from stockviz.services.screener import (
    MAX_MOMENTUM_DAYS,
    NEAR_52W_THRESHOLD,  # noqa: F401  (re-exported for older imports)
    SORT_KEYS,
    ScreenQuery,
    run_screen,
)

router = APIRouter(prefix="/v1/symbols", tags=["screener"])
page_router = APIRouter(prefix="/v1", tags=["screener"])

SessionDep = Annotated[Session, Depends(get_session)]

MAX_RESULTS = 200
MAX_PAGE = 100


def _csv(raw: str | None) -> list[str]:
    return [p.strip() for p in (raw or "").split(",") if p.strip()]


@page_router.get("/screener", response_model=ScreenerPageOut)
@limiter.limit("30/minute")
def screener(
    request: Request,
    session: SessionDep,
    market: Annotated[str | None, Query(description="Countries, e.g. US,IN")] = None,
    exchange: Annotated[str | None, Query(description="MICs, e.g. XNAS,XNSE")] = None,
    currency: Annotated[str | None, Query(description="e.g. USD,INR")] = None,
    sector: Annotated[str | None, Query()] = None,
    rsi_min: Annotated[float | None, Query(ge=0, le=100)] = None,
    rsi_max: Annotated[float | None, Query(ge=0, le=100)] = None,
    momentum_days: Annotated[int | None, Query(ge=1, le=MAX_MOMENTUM_DAYS)] = None,
    momentum_min: Annotated[float | None, Query()] = None,
    momentum_max: Annotated[float | None, Query()] = None,
    near_52w_high: Annotated[bool, Query()] = False,
    near_52w_low: Annotated[bool, Query()] = False,
    above_sma_50: Annotated[bool | None, Query()] = None,
    above_sma_200: Annotated[bool | None, Query()] = None,
    hv_min: Annotated[float | None, Query(ge=0)] = None,
    hv_max: Annotated[float | None, Query(ge=0)] = None,
    atr_pct_min: Annotated[float | None, Query(ge=0)] = None,
    atr_pct_max: Annotated[float | None, Query(ge=0)] = None,
    sentiment_min: Annotated[float | None, Query(ge=-1, le=1)] = None,
    sentiment_max: Annotated[float | None, Query(ge=-1, le=1)] = None,
    sort: Annotated[str, Query(pattern="^(" + "|".join(SORT_KEYS) + ")$")] = "ticker",
    dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 50,
) -> ScreenerPageOut:
    rows, total = run_screen(
        session,
        ScreenQuery(
            markets=_csv(market),
            exchanges=_csv(exchange),
            currencies=_csv(currency),
            sector=sector,
            rsi_min=rsi_min,
            rsi_max=rsi_max,
            momentum_days=momentum_days,
            momentum_min=momentum_min,
            momentum_max=momentum_max,
            near_52w_high=near_52w_high,
            near_52w_low=near_52w_low,
            above_sma_50=above_sma_50,
            above_sma_200=above_sma_200,
            hv_min=hv_min,
            hv_max=hv_max,
            atr_pct_min=atr_pct_min,
            atr_pct_max=atr_pct_max,
            sentiment_min=sentiment_min,
            sentiment_max=sentiment_max,
            sort=sort,
            descending=dir == "desc",
            offset=offset,
            limit=limit,
        ),
    )
    return ScreenerPageOut(
        rows=[ScreenerRowOut.model_validate(r, from_attributes=True) for r in rows],
        total=total,
        offset=offset,
        limit=limit,
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
    sentiment_min: Annotated[float | None, Query(ge=-1, le=1)] = None,
    sentiment_max: Annotated[float | None, Query(ge=-1, le=1)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_RESULTS)] = MAX_RESULTS,
) -> list[ScreenerResultOut]:
    """The original list screen, on the unified query path (RS-5 fixed)."""
    rows, _total = run_screen(
        session,
        ScreenQuery(
            sector=sector,
            rsi_min=rsi_min,
            rsi_max=rsi_max,
            momentum_days=momentum_days,
            momentum_min=momentum_min,
            momentum_max=momentum_max,
            near_52w_high=near_52w_high,
            near_52w_low=near_52w_low,
            sentiment_min=sentiment_min,
            sentiment_max=sentiment_max,
            limit=limit,
        ),
    )
    return [
        ScreenerResultOut(
            ticker=r.ticker,
            name=r.name,
            sector=r.sector,
            exchange=r.exchange,
            currency=r.currency,
            last_close=r.last_close,
            as_of=r.as_of,
            rsi_14=r.rsi_14,
            momentum_pct=r.momentum_pct,
            momentum_days=r.momentum_days,
            high_52w=r.high_52w,
            low_52w=r.low_52w,
            sentiment_7d=r.sentiment_7d,
        )
        for r in rows
        # A metrics row always has these (it is written from at least one
        # bar); a row without them is skipped, never shown as 0 (RS-4).
        if r.last_close is not None and r.high_52w is not None and r.low_52w is not None
    ]
