"""`GET /v1/breadth`: market breadth and diffusion per session (A7.1, M3.3).

Public, 60/min, computed on read from stored daily bars and cached in process
for ten minutes (``services/breadth.py`` holds every formula).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlmodel import Session

from stockviz.db import get_session
from stockviz.limiter import limiter
from stockviz.schemas import BreadthOut, BreadthPointOut
from stockviz.services import breadth as svc

router = APIRouter(prefix="/v1", tags=["breadth"])

SessionDep = Annotated[Session, Depends(get_session)]
MAX_DAYS = 3660


@router.get("/breadth", response_model=BreadthOut)
@limiter.limit("60/minute")
def get_breadth(
    request: Request,
    response: Response,
    session: SessionDep,
    market: Literal["US", "IN"] = "US",
    start: Annotated[date | None, Query(alias="from")] = None,
    end: Annotated[date | None, Query(alias="to")] = None,
) -> BreadthOut:
    end = end or date.today()
    start = start or end - timedelta(days=365)
    if start > end:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "from must be on or before to")
    if (end - start).days > MAX_DAYS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "at most 10 years at a time")
    result = svc.breadth(session, market, start, end)
    response.headers["Cache-Control"] = f"public, max-age={svc.CACHE_SECONDS}"
    return BreadthOut(
        market=market,
        start=start,
        end=end,
        members=result.members,
        universe_note=svc.UNIVERSE_NOTE,
        method=svc.METHOD,
        points=[BreadthPointOut.model_validate(p) for p in result.points],
    )
