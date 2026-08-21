"""`/v1/symbols/screen` — filter the symbol universe by technical criteria.

Filters read the precomputed ``symbol_metrics`` table rather than rescanning
``price_bars``. The previous version pulled ~260 bars per symbol and recomputed
RSI for the whole universe on every request — around 8,300 rows scanned per
call, uncached and uncapped. Metrics are refreshed once a day by the scheduler
(``services/metrics.py``), right after prices land, so a screen is now a single
indexed query.

All filters are AND'd. A symbol whose metric is NULL (not enough history, or
the refresh hasn't run for it yet) does not match a filter on that metric.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func
from sqlmodel import Session, select

from stockviz.db import get_session
from stockviz.limiter import limiter
from stockviz.models import PriceBar, Symbol, SymbolMetrics
from stockviz.schemas import ScreenerResultOut

router = APIRouter(prefix="/v1/symbols", tags=["screener"])

SessionDep = Annotated[Session, Depends(get_session)]

NEAR_52W_THRESHOLD = Decimal("0.05")
"""How close to the 52-week extreme we count as ``near``. 5% by default."""

MAX_RESULTS = 200
MAX_MOMENTUM_DAYS = 252


def _momentum_by_ticker(
    session: Session, tickers: list[str], *, days: int
) -> dict[str, float | None]:
    """N-day return per ticker, from one windowed query over ``price_bars``.

    Momentum needs exactly two closes — the latest and the one ``days`` bars
    back — so there is no reason to scan a year of history per symbol. Keeping
    it computed (rather than materialized like RSI) preserves the arbitrary
    ``momentum_days`` the endpoint has always accepted.
    """
    if not tickers:
        return {}

    ranked = (
        select(
            PriceBar.ticker,
            PriceBar.close,  # type: ignore[arg-type]
            func.row_number()
            .over(
                partition_by=PriceBar.ticker,  # type: ignore[arg-type]
                order_by=PriceBar.ts.desc(),  # type: ignore[attr-defined]
            )
            .label("rn"),
        )
        .where(
            PriceBar.ticker.in_(tickers),  # type: ignore[attr-defined]
            PriceBar.interval == "1d",
        )
        .subquery()
    )
    rows = session.exec(
        select(ranked.c.ticker, ranked.c.rn, ranked.c.close).where(  # type: ignore[call-overload]
            ranked.c.rn.in_([1, days + 1])
        )
    ).all()

    latest: dict[str, Decimal] = {}
    prior: dict[str, Decimal] = {}
    for ticker, rn, close in rows:
        (latest if rn == 1 else prior)[ticker] = close

    out: dict[str, float | None] = {}
    for ticker in tickers:
        now, then = latest.get(ticker), prior.get(ticker)
        out[ticker] = (
            float((now - then) / then * 100) if now is not None and then not in (None, 0) else None
        )
    return out


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
    """Screen the universe against the precomputed metrics."""
    stmt = (
        select(SymbolMetrics, Symbol)
        .join(Symbol, Symbol.ticker == SymbolMetrics.ticker)  # type: ignore[arg-type]
        .where(Symbol.is_active)
    )

    if sector is not None:
        stmt = stmt.where(Symbol.sector == sector)
    if rsi_min is not None:
        stmt = stmt.where(SymbolMetrics.rsi_14 >= rsi_min)  # type: ignore[arg-type]
    if rsi_max is not None:
        stmt = stmt.where(SymbolMetrics.rsi_14 <= rsi_max)  # type: ignore[arg-type]

    if near_52w_high:
        stmt = stmt.where(
            SymbolMetrics.high_52w.is_not(None),  # type: ignore[union-attr]
            SymbolMetrics.last_close >= SymbolMetrics.high_52w * (Decimal(1) - NEAR_52W_THRESHOLD),  # type: ignore[operator]
        )
    if near_52w_low:
        stmt = stmt.where(
            SymbolMetrics.low_52w.is_not(None),  # type: ignore[union-attr]
            SymbolMetrics.last_close <= SymbolMetrics.low_52w * (Decimal(1) + NEAR_52W_THRESHOLD),  # type: ignore[operator]
        )

    if sentiment_min is not None:
        stmt = stmt.where(SymbolMetrics.sentiment_7d >= sentiment_min)  # type: ignore[arg-type]
    if sentiment_max is not None:
        stmt = stmt.where(SymbolMetrics.sentiment_7d <= sentiment_max)  # type: ignore[arg-type]

    stmt = stmt.order_by(SymbolMetrics.ticker).limit(limit)  # type: ignore[arg-type]
    candidates = list(session.exec(stmt).all())

    # Momentum is applied after the indexed filters, over the surviving set
    # only, so the extra query stays small.
    momentum_by_ticker: dict[str, float | None] = {}
    if momentum_days is not None:
        momentum_by_ticker = _momentum_by_ticker(
            session, [s.ticker for _m, s in candidates], days=momentum_days
        )

    results: list[ScreenerResultOut] = []
    for metrics, symbol in candidates:
        momentum_pct = momentum_by_ticker.get(symbol.ticker) if momentum_days else None
        if momentum_days is not None:
            if momentum_pct is None:
                continue
            if momentum_min is not None and momentum_pct < momentum_min:
                continue
            if momentum_max is not None and momentum_pct > momentum_max:
                continue
        results.append(
            ScreenerResultOut(
                ticker=symbol.ticker,
                name=symbol.name,
                sector=symbol.sector,
                exchange=symbol.exchange,
                currency=symbol.currency,
                last_close=metrics.last_close or Decimal(0),
                rsi_14=metrics.rsi_14,
                momentum_pct=momentum_pct,
                momentum_days=momentum_days,
                high_52w=metrics.high_52w or Decimal(0),
                low_52w=metrics.low_52w or Decimal(0),
                sentiment_7d=metrics.sentiment_7d,
            )
        )
    return results
