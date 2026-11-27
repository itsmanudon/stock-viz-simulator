"""`POST /v1/research/optimise` (A7.11, M10.6): weights over stored closes.

Public, 10 a minute (the solvers cost CPU). Nothing is placed or stored.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlmodel import Session

from stockviz.db import get_session
from stockviz.limiter import limiter
from stockviz.schemas import OptimiseIn, OptimiseOut, OptimisePerformanceOut, OptimiseWeightOut
from stockviz.services import optimise as opt

router = APIRouter(prefix="/v1/research", tags=["research"])

SessionDep = Annotated[Session, Depends(get_session)]

DISCLAIMER = (
    "Weights fitted to the stored past, in-sample. Not a recommendation, not advice, and "
    "not point in time: the symbol list is yours, chosen today."
)


@router.post("/optimise", response_model=OptimiseOut)
@limiter.limit("10/minute")
def optimise(request: Request, body: OptimiseIn, session: SessionDep) -> OptimiseOut:
    del request
    tickers = list(dict.fromkeys(t.strip().upper() for t in body.tickers if t.strip()))
    if len(tickers) < 2:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "give at least two different symbols")
    try:
        closes, currency = opt.load_closes(session, tickers, body.years)
        caps = opt.market_caps(session, tickers) if body.method == "black_litterman" else None
        result = opt.optimise(
            closes,
            currency,
            body.method,
            risk_free_rate=body.risk_free_rate,
            max_weight=body.max_weight,
            beta=body.beta,
            cash=body.cash,
            market_caps=caps,
            views=[opt.View(v.ticker.upper(), v.expected_return, v.confidence) for v in body.views],
            delta=body.delta,
        )
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown symbol: {exc}") from exc
    except opt.OptimiseError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return OptimiseOut(
        method=result.method,
        currency=result.currency,
        first=result.first,
        last=result.last,
        sessions=result.sessions,
        risk_free_rate=body.risk_free_rate,
        beta=body.beta,
        weights=[
            OptimiseWeightOut(
                ticker=t,
                weight=result.weights[t],
                shares=result.allocation.get(t) if result.allocation else None,
                price=result.prices.get(t),
                prior=(result.prior or {}).get(t),
                posterior=(result.posterior or {}).get(t),
            )
            for t in result.tickers
        ],
        performance=OptimisePerformanceOut(
            expected_return=result.expected_return,
            volatility=result.volatility,
            sharpe=result.sharpe,
            cvar=result.cvar,
        ),
        equal_weight=OptimisePerformanceOut(**result.equal_weight),
        cash=body.cash,
        leftover=result.leftover,
        notes=result.notes,
        disclaimer=DISCLAIMER,
    )
