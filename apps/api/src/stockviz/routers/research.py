"""`/v1/research/event-study` — price reactions to news (Phase 7.4).

Public and rate-limited like the screener. See ``services/event_study.py``
for the method: market-adjusted abnormal returns around the first session
that closed after each matching Aegis document became available.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlmodel import Session

from stockviz.db import get_session
from stockviz.limiter import limiter
from stockviz.models import Symbol
from stockviz.schemas import (
    EventStudyEventOut,
    EventStudyOut,
    EventStudyPointOut,
    EventStudyWindowOut,
)
from stockviz.services.event_study import MIN_EVENTS, run_event_study

router = APIRouter(prefix="/v1/research", tags=["research"])

SessionDep = Annotated[Session, Depends(get_session)]

MAX_TICKERS = 20


def _pct(value: float | None) -> float | None:
    return None if value is None else round(value * 100, 4)


@router.get("/event-study", response_model=EventStudyOut)
@limiter.limit("20/minute")
def event_study(
    request: Request,
    session: SessionDep,
    tickers: Annotated[list[str], Query(min_length=1)],
    sentiment: Literal["negative", "positive", "mixed", "neutral"] | None = None,
    event_type: Annotated[str | None, Query(max_length=128)] = None,
    pre: Annotated[int, Query(ge=1, le=20)] = 5,
    post: Annotated[int, Query(ge=1, le=60)] = 20,
) -> EventStudyOut:
    """``tickers`` may repeat (``?tickers=A&tickers=B``) or be comma-separated."""
    names = sorted({t.strip().upper() for raw in tickers for t in raw.split(",") if t.strip()})
    if not names or len(names) > MAX_TICKERS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"give between 1 and {MAX_TICKERS} tickers"
        )
    unknown = [t for t in names if session.get(Symbol, t) is None]
    if unknown:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown symbols: {', '.join(unknown)}")
    study = run_event_study(
        session,
        tickers=names,
        sentiment=sentiment,
        event_type=event_type or None,
        pre=pre,
        post=post,
    )
    return EventStudyOut(
        tickers=study.tickers,
        sentiment=study.sentiment,
        event_type=study.event_type,
        pre=study.pre,
        post=study.post,
        benchmarks=study.benchmarks,
        no_benchmark=study.no_benchmark,
        min_events=MIN_EVENTS,
        enough=study.enough,
        events_found=study.events_found,
        events_used=study.events_used,
        events_incomplete=study.events_incomplete,
        overlapping=study.overlapping,
        windows=[
            EventStudyWindowOut(
                start=w.start,
                end=w.end,
                mean_car_pct=_pct(w.mean_car),
                std_error_pct=_pct(w.std_error),
                t_stat=None if w.t_stat is None else round(w.t_stat, 3),
            )
            for w in study.windows
        ],
        path=[
            EventStudyPointOut(offset=o, mean_car_pct=_pct(m), std_error_pct=_pct(se))
            for o, m, se in study.path
        ],
        events=[
            EventStudyEventOut(
                ticker=e.ticker,
                document_id=e.document_id,
                title=e.title,
                available_at=e.available_at,
                event_date=e.event_date,
                car_pct=round(e.car * 100, 4),
            )
            for e in study.events[:100]
        ],
    )
