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

from stockviz.db import get_session
from stockviz.limiter import limiter
from stockviz.schemas import BacktestIn, BacktestOut
from stockviz.services.backtest import BacktestError
from stockviz.services.backtest.run import BadRange, UnknownSymbol, execute_backtest

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
