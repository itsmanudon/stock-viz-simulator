"""`POST /v1/backtest` — replay stored bars through a strategy spec.

A pure what-if computation, so it's a public endpoint (no auth) gated only by
the shared rate limiter. The strategy spec is a discriminated union — see
``schemas.StrategySpec`` — and only the two v1 types (``rsi_threshold`` and
``sma_crossover``) are accepted. Bars come from the ``price_bars`` table; no
external API is hit.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session

from stockviz.auth import OptionalUserIdDep
from stockviz.db import get_session
from stockviz.limiter import limiter
from stockviz.schemas import BacktestIn, BacktestOut, StrategyBacktestIn, StrategyBacktestOut
from stockviz.services.backtest import BacktestError
from stockviz.services.backtest.run import BadRange, UnknownSymbol, execute_backtest
from stockviz.services.backtest.strategy import StrategyError
from stockviz.services.backtest.strategy_run import (
    StrategyNeedsUser,
    StrategyNotFound,
    execute_strategy,
)
from stockviz.services.dsl import RuleError
from stockviz.services.setups.rules import error_out

router = APIRouter(prefix="/v1", tags=["backtest"])

SessionDep = Annotated[Session, Depends(get_session)]


@router.post("/backtest", response_model=BacktestOut)
@limiter.limit("20/minute")
def post_backtest(request: Request, body: BacktestIn, session: SessionDep) -> BacktestOut:
    try:
        return execute_backtest(session, body).out
    except UnknownSymbol as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (BadRange, BacktestError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def strategy_http_error(exc: Exception) -> HTTPException:
    """The status a strategy failure maps to (shared with the registry router)."""
    if isinstance(exc, StrategyNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, StrategyNeedsUser):
        return HTTPException(status_code=401, detail=str(exc))
    if isinstance(exc, RuleError):
        return HTTPException(status_code=422, detail=error_out(exc).model_dump())
    return HTTPException(status_code=400, detail=str(exc))


STRATEGY_ERRORS = (StrategyNotFound, StrategyNeedsUser, RuleError, StrategyError)


@router.post("/backtest/strategy", response_model=StrategyBacktestOut)
@limiter.limit("20/minute")
def post_strategy_backtest(
    request: Request, body: StrategyBacktestIn, session: SessionDep, user_id: OptionalUserIdDep
) -> StrategyBacktestOut:
    """A4.1: the strategy mode of the backtester. A Rule DSL entry (and
    optional exit) rule, stops, sizing and a universe (one ticker, a
    watchlist of yours, or up to 50 tickers). Public: a watchlist, your own
    setup version or a rule that reads drawings need a Bearer token."""
    try:
        return execute_strategy(session, body, user_id=user_id).out
    except STRATEGY_ERRORS as exc:
        raise strategy_http_error(exc) from exc
