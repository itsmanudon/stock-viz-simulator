"""`POST /v1/backtest` — replay stored bars through a strategy spec.

A pure what-if computation, so it's a public endpoint (no auth) gated only by
the shared rate limiter. The strategy spec is a discriminated union — see
``schemas.StrategySpec`` — and only the two v1 types (``rsi_threshold`` and
``sma_crossover``) are accepted. Bars come from the ``price_bars`` table; no
external API is hit.
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session, select

from stockviz.db import get_session
from stockviz.limiter import limiter
from stockviz.models import PriceBar, Symbol
from stockviz.schemas import (
    BacktestIn,
    BacktestOut,
    BacktestSummaryOut,
    BacktestTradeOut,
    EquityPointOut,
    RsiThresholdStrategy,
    SmaCrossoverStrategy,
)
from stockviz.services.backtest import BacktestError, run_backtest

router = APIRouter(prefix="/v1", tags=["backtest"])

SessionDep = Annotated[Session, Depends(get_session)]


@router.post("/backtest", response_model=BacktestOut)
@limiter.limit("20/minute")
def post_backtest(request: Request, body: BacktestIn, session: SessionDep) -> BacktestOut:
    ticker = body.ticker.upper()
    if session.get(Symbol, ticker) is None:
        raise HTTPException(status_code=404, detail=f"Symbol {ticker!r} not found")
    if body.from_ > body.to:
        raise HTTPException(status_code=400, detail="'from' must be on or before 'to'")

    # Inclusive date range — bars are stored at day granularity (interval 1d).
    start = datetime.combine(body.from_, time.min)
    end = datetime.combine(body.to, time.max)
    stmt = (
        select(PriceBar)
        .where(
            PriceBar.ticker == ticker,
            PriceBar.interval == "1d",
            PriceBar.ts >= start,
            PriceBar.ts <= end,
        )
        .order_by(PriceBar.ts.asc())  # type: ignore[attr-defined]
    )
    rows = list(session.exec(stmt).all())
    bars = [(r.ts, r.close) for r in rows]

    if isinstance(body.strategy, RsiThresholdStrategy):
        strategy_type = "rsi_threshold"
        params: dict = {
            "buy_below": body.strategy.buy_below,
            "sell_above": body.strategy.sell_above,
        }
    elif isinstance(body.strategy, SmaCrossoverStrategy):
        strategy_type = "sma_crossover"
        params = {
            "short_window": body.strategy.short_window,
            "long_window": body.strategy.long_window,
        }
    else:  # pragma: no cover - discriminated union guarantees one of the above
        raise HTTPException(status_code=400, detail="Unsupported strategy type")

    try:
        result = run_backtest(
            bars,
            initial_cash=body.initial_cash,
            strategy_type=strategy_type,
            params=params,
            commission_bps=body.commission_bps,
            slippage_bps=body.slippage_bps,
        )
    except BacktestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return BacktestOut(
        ticker=ticker,
        trades=[
            BacktestTradeOut(date=t.date, side=t.side, price=t.price, shares=t.shares)  # type: ignore[arg-type]
            for t in result.trades
        ],
        equity_curve=[EquityPointOut(date=p.date, nav=p.nav) for p in result.equity_curve],
        summary=BacktestSummaryOut(
            total_return=result.summary.total_return,
            sharpe=result.summary.sharpe,
            max_drawdown=result.summary.max_drawdown,
            final_nav=result.summary.final_nav,
            benchmark_return=result.summary.benchmark_return,
            benchmark_final_nav=result.summary.benchmark_final_nav,
            excess_return=result.summary.excess_return,
            total_costs=result.summary.total_costs,
        ),
    )
