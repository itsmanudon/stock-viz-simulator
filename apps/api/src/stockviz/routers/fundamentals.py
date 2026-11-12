"""`/v1/symbols/{ticker}/fundamentals` — statements as known on a date (Phase 6.3).

Columns are the latest ``periods`` annual or quarterly period ends; rows are
the normalised concepts (``services/fundamentals/concepts.py``). Balance-sheet
lines are read at each period's end. Every figure is the version known on
``as_of`` (default today), so a past date shows what was public then, to the
extent the source records it (``point_in_time``).
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlmodel import Session

from stockviz._time import utcnow
from stockviz.db import get_session
from stockviz.limiter import limiter
from stockviz.models import Symbol
from stockviz.schemas import FundamentalRowOut, FundamentalsOut
from stockviz.services.fundamentals.concepts import CONCEPTS
from stockviz.services.fundamentals.store import facts_as_of
from stockviz.services.instruments import instrument_ids

router = APIRouter(prefix="/v1/symbols", tags=["fundamentals"])

SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/{ticker}/fundamentals", response_model=FundamentalsOut)
@limiter.limit("60/minute")
def get_fundamentals(
    request: Request,
    ticker: str,
    session: SessionDep,
    period: Annotated[str, Query(pattern="^(annual|quarter)$")] = "annual",
    as_of: Annotated[date | None, Query()] = None,
    periods: Annotated[int, Query(ge=1, le=20)] = 5,
) -> FundamentalsOut:
    ticker = ticker.upper()
    if session.get(Symbol, ticker) is None:
        raise HTTPException(status_code=404, detail=f"Symbol {ticker!r} not found")
    day = as_of or utcnow().date()
    instrument_id = instrument_ids(session, [ticker]).get(ticker)
    known = facts_as_of(session, instrument_id, day) if instrument_id is not None else {}

    ends = sorted({end for (_c, ptype, end) in known if ptype == period}, reverse=True)[:periods]
    rows: list[FundamentalRowOut] = []
    used = []
    for key, concept in CONCEPTS.items():
        ptype = "instant" if concept.kind == "stock" else period
        facts = [known.get((key, ptype, end)) for end in ends]
        if not any(facts):
            continue
        used.extend(f for f in facts if f is not None)
        unit = next(f.unit for f in facts if f is not None)
        rows.append(
            FundamentalRowOut(
                concept=key,
                label=concept.label,
                unit=unit,
                values=[f.value if f is not None else None for f in facts],
            )
        )
    currencies = {f.currency for f in used if f.currency}
    return FundamentalsOut(
        ticker=ticker,
        period=period,  # type: ignore[arg-type]
        as_of=day,
        currency=currencies.pop() if len(currencies) == 1 else None,
        periods=ends,
        rows=rows,
        sources=sorted({f.source for f in used}),
        point_in_time=bool(used) and all(f.point_in_time for f in used),
        latest_available_at=max((f.available_at for f in used), default=None),
    )
