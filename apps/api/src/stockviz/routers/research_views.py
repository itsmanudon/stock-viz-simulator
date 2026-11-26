"""A9 research views on stored data (public, 60/min).

- `GET /v1/symbols/{t}/seasonality` (A9.1, M3.6)
- `GET /v1/symbols/{t}/earnings-drift` (A9.1, M6.6)
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlmodel import Session

from stockviz.db import get_session
from stockviz.limiter import limiter
from stockviz.models import Symbol
from stockviz.schemas import EarningsDriftOut, SeasonalityOut
from stockviz.services import seasonality as svc

router = APIRouter(prefix="/v1/symbols", tags=["research"])

SessionDep = Annotated[Session, Depends(get_session)]

SEASON_NOTE = (
    "Stored history, percent returns. Association, not a forecast: a month's average "
    "can be one big year; months under 10 years of data are marked thin."
)
DRIFT_NOTE = (
    "Reaction: the first session after the report (before the open: that day; after the "
    "close: the next; unknown time: the event day, marked assumed). Drift is measured from "
    "the reaction close."
)


def _symbol(session: Session, ticker: str) -> str:
    ticker = ticker.upper()
    if session.get(Symbol, ticker) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Symbol {ticker!r} not found")
    return ticker


@router.get("/{ticker}/seasonality", response_model=SeasonalityOut)
@limiter.limit("60/minute")
def get_seasonality(request: Request, ticker: str, session: SessionDep) -> SeasonalityOut:
    del request
    ticker = _symbol(session, ticker)
    result = svc.seasonality(svc.closes(session, ticker))
    return SeasonalityOut.model_validate({"ticker": ticker, "note": SEASON_NOTE, **result})


@router.get("/{ticker}/earnings-drift", response_model=EarningsDriftOut)
@limiter.limit("60/minute")
def get_earnings_drift(request: Request, ticker: str, session: SessionDep) -> EarningsDriftOut:
    del request
    ticker = _symbol(session, ticker)
    d = svc.earnings_drift(svc.closes(session, ticker), svc.events_for(session, ticker))
    return EarningsDriftOut.model_validate({
        "ticker": ticker, "note": DRIFT_NOTE, "avg_abs_reaction": d.avg_abs_reaction,
        "avg_abs_day": d.avg_abs_day, "events": d.events, "groups": d.groups,
    })  # fmt: skip
