"""`GET /v1/fo/india` (A7.14, M6.1, M6.3): India index options summaries.

Read-only and public; the rows exist only where the owner's files were loaded
(a local database). Nothing here reads a file or calls an exchange.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlmodel import Session

from stockviz.db import get_session
from stockviz.limiter import limiter
from stockviz.schemas import FoDayOut, FoIndiaOut, FoSmileOut, FoUnderlyingOut
from stockviz.services.fo import summary

router = APIRouter(prefix="/v1/fo", tags=["fo"])

SessionDep = Annotated[Session, Depends(get_session)]

SOURCE_NOTE = (
    "From the owner's minute files, loaded into a local database only. Strikes are offsets "
    "from the money each minute; expiries are not in the files; IV is the files' own."
)


@router.get("/india", response_model=FoIndiaOut)
@limiter.limit("60/minute")
def fo_india(request: Request, session: SessionDep) -> FoIndiaOut:
    del request
    out = []
    for s in summary.load_summaries(session):
        out.append(
            FoUnderlyingOut(
                underlying=s.underlying,
                series=s.series,
                first=s.first,
                last=s.last,
                sessions=len(s.days),
                iv_now=s.iv_now,
                iv_rank=s.iv_rank,
                iv_percentile=s.iv_percentile,
                days=[
                    FoDayOut(day=p.day, atm_iv=p.atm_iv, skew=p.skew, pcr=p.pcr, spot=p.spot)
                    for p in s.days
                ],
                smile=[FoSmileOut(offset=o, call_iv=c, put_iv=p) for o, c, p in s.smile],
            )
        )
    return FoIndiaOut(
        underlyings=out,
        skew_offset=summary.SKEW_OFFSET,
        min_days=summary.MIN_DAYS,
        method=" ".join((summary.__doc__ or "").split("\n\n", 1)[-1].split()),
        source_note=SOURCE_NOTE,
    )
