"""`GET /v1/sector-rotation`: the sector rotation map (A7.2, M3.2).

Public, 60/min. Weekly RS-Trend against RS-Momentum per sector, from stored
daily bars (``services/sector_rotation.py`` holds the maths).
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlmodel import Session

from stockviz.db import get_session
from stockviz.limiter import limiter
from stockviz.schemas import RotationOut, RotationPointOut, RotationSectorOut
from stockviz.services import sector_rotation as svc

router = APIRouter(prefix="/v1", tags=["sector-rotation"])

SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/sector-rotation", response_model=RotationOut)
@limiter.limit("60/minute")
def get_sector_rotation(
    request: Request,
    response: Response,
    session: SessionDep,
    market: Literal["US", "IN"] = "US",
    weeks: Annotated[int, Query(ge=2, le=26)] = 10,
) -> RotationOut:
    result = svc.rotation(session, market, weeks=weeks)
    response.headers["Cache-Control"] = "public, max-age=600"
    return RotationOut(
        market=market,
        benchmark=result.benchmark,
        benchmark_name=result.benchmark_name,
        as_of=result.as_of,
        note=svc.NOTE,
        method=svc.METHOD,
        sectors=[
            RotationSectorOut(
                sector=s.sector,
                members=s.members,
                points=[RotationPointOut.model_validate(p) for p in s.points],
            )
            for s in result.sectors
        ],
    )
