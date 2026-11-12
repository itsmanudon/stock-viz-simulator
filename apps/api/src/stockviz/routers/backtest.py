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
from stockviz.models import Dividend, PriceBar, Symbol
from stockviz.schemas import (
    BacktestFeeOut,
    BacktestIn,
    BacktestOut,
    BacktestSummaryOut,
    BacktestTradeOut,
    EquityPointOut,
    RsiThresholdStrategy,
    SmaCrossoverStrategy,
)
from stockviz.services.backtest import BacktestError, run_backtest, warmup_bars_for
from stockviz.services.backtest.engine import FILL_RULES
from stockviz.services.instruments import instrument_of

router = APIRouter(prefix="/v1", tags=["backtest"])

SessionDep = Annotated[Session, Depends(get_session)]


@router.post("/backtest", response_model=BacktestOut)
@limiter.limit("20/minute")
def post_backtest(request: Request, body: BacktestIn, session: SessionDep) -> BacktestOut:
    ticker = body.ticker.upper()
    symbol = session.get(Symbol, ticker)
    if symbol is None:
        raise HTTPException(status_code=404, detail=f"Symbol {ticker!r} not found")
    if body.from_ > body.to:
        raise HTTPException(status_code=400, detail="'from' must be on or before 'to'")

    # Inclusive date range — bars are stored at day granularity (interval 1d).
    start = datetime.combine(body.from_, time.min)
    end = datetime.combine(body.to, time.max)
    stmt = (
        select(PriceBar)
        .where(
            PriceBar.instrument_id == instrument_of(ticker),
            PriceBar.interval == "1d",
            PriceBar.ts >= start,
            PriceBar.ts <= end,
        )
        .order_by(PriceBar.ts.asc())  # type: ignore[attr-defined]
    )
    rows = list(session.exec(stmt).all())

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

    # Warm-up (audit SR-3): the bars before ``from`` the strategy needs, read
    # but not traded, so its first signal inside the window is a real one.
    warmup = list(
        reversed(
            session.exec(
                select(PriceBar)
                .where(
                    PriceBar.instrument_id == instrument_of(ticker),
                    PriceBar.interval == "1d",
                    PriceBar.ts < start,
                )
                .order_by(PriceBar.ts.desc())  # type: ignore[attr-defined]
                .limit(warmup_bars_for(strategy_type, params))
            ).all()
        )
    )
    used = warmup + rows
    bars = [(r.ts, r.close) for r in used]
    opens = {r.ts: r.open for r in used}
    bases = {r.adjustment_semantics for r in used}
    price_basis = None if not bases else bases.pop() if len(bases) == 1 else "mixed"

    dividends = None
    if body.return_mode == "total":
        dividends = {
            d.ex_date: d.amount
            for d in session.exec(
                select(Dividend).where(
                    Dividend.instrument_id == instrument_of(ticker),
                    Dividend.ex_date >= body.from_,
                    Dividend.ex_date <= body.to,
                )
            ).all()
        }

    try:
        result = run_backtest(
            bars,
            initial_cash=body.initial_cash,
            strategy_type=strategy_type,
            params=params,
            commission_bps=body.commission_bps,
            slippage_bps=body.slippage_bps,
            trade_from=start,
            dividends=dividends,
            opens=opens,
            fill_rule=body.fill_rule,
            spread_bps=body.spread_bps,
            fee_schedule=body.fee_schedule,
        )
    except BacktestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return BacktestOut(
        ticker=ticker,
        currency=symbol.currency or "USD",
        price_basis=str(price_basis) if price_basis is not None else None,
        return_mode=body.return_mode,
        warmup_bars=len(warmup),
        execution_profile=f"{FILL_RULES[body.fill_rule].name}/{FILL_RULES[body.fill_rule].model_version}",
        fee_schedule=body.fee_schedule,
        trades=[
            BacktestTradeOut(
                date=t.date,
                side=t.side,  # type: ignore[arg-type]
                price=t.price,
                shares=t.shares,
                reference_price=t.reference_price,
                fees=[BacktestFeeOut(name=n, amount=a) for n, a in t.fees],
            )
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
