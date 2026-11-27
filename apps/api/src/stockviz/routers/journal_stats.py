"""`/v1/journal/stats` (A5.6, M10.3): "Is my edge real?" over the journal.

Authed, private to the owner; another user's book is 404. Every figure is
computed on read from the closed journal entries (``services/journal/edge.py``
holds the definitions, the seeded bootstrap and the under-30 rule).

- ``book``: an id keeps that book's entries; omitted or ``all`` reads every
  book and your replay sessions.
- ``source``: omitted = paper and imported (your trades; replay is never
  pooled with them by default), ``paper``, ``imported``, ``replay``, or
  ``all`` (the three pooled). The by-source groups ignore it.
- ``setup_version_id`` (the plan's), ``tag`` (setup or mistake tag, ignoring
  case), ``from``/``to`` (the entry's venue date).
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session

from stockviz.auth import UserIdDep
from stockviz.db import get_session
from stockviz.routers.book_query import BookOrAllQuery, parse_book
from stockviz.schemas import BehaviourOut, EdgeStatsOut, LookAtOut, WeekFiguresOut, WeeklyReviewOut
from stockviz.services.journal import edge
from stockviz.services.trading.books import resolve_book

router = APIRouter(prefix="/v1/journal", tags=["journal"])

SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/stats", response_model=EdgeStatsOut)
def journal_stats(
    session: SessionDep,
    user_id: UserIdDep,
    book: BookOrAllQuery = None,
    source: Literal["paper", "imported", "replay", "all"] | None = None,
    setup_version_id: Annotated[int | None, Query(ge=1)] = None,
    tag: Annotated[str | None, Query(min_length=1, max_length=32)] = None,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
) -> EdgeStatsOut:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "`from` is after `to`")
    chosen = parse_book(book)
    filters = edge.EdgeFilters(
        book_id=chosen if isinstance(chosen, int) else None,
        source=source,
        setup_version_id=setup_version_id,
        tag=tag,
        date_from=date_from,
        date_to=date_to,
    )
    return edge.edge_stats(session, user_id, filters)


BEHAVIOUR_METHOD = {
    "discipline": "Share of entries with a plan locked before entry that followed it",
    "disposition_index": "Mean holding days of losers / mean holding days of winners",
    "tilt": "Opened after a losing close at more than 1.5x the median size of the 20 "
    "entries before it",
    "heatmap": "By weekday and hour of the first fill, in the venue's time zone",
    "cost_leakage": "Fees (estimated for imports) in total, per entry and over gross P&L",
    "wording": "Describes the record; not advice",
}


@router.get("/behaviour", response_model=BehaviourOut)
def journal_behaviour(
    session: SessionDep,
    user_id: UserIdDep,
    book: BookOrAllQuery = None,
    source: Literal["paper", "imported", "replay", "all"] | None = None,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
) -> BehaviourOut:
    """A7.6 (M10.4): discipline, disposition, tilt, heatmaps and cost leakage."""
    from stockviz.services.journal.behaviour import behaviour

    if date_from and date_to and date_from > date_to:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "`from` is after `to`")
    chosen = parse_book(book)
    filters = edge.EdgeFilters(
        book_id=chosen if isinstance(chosen, int) else None,
        source=source,
        date_from=date_from,
        date_to=date_to,
    )
    if filters.book_id is not None:
        resolve_book(session, user_id, filters.book_id)
    kept = [o for o in edge.collect_outcomes(session, user_id).outcomes
            if edge._keep(o, filters)]  # fmt: skip
    result = behaviour(kept)
    return BehaviourOut(**result.__dict__, method=BEHAVIOUR_METHOD)  # type: ignore[arg-type]


WEEKLY_METHOD = (
    "Entries closed in the seven days ending week_end (UTC), against the four weeks before. "
    "Items to look at come from fixed rules: size after a losing close (more than 1.5x the "
    "recent median), scored plans not followed, no plan locked before entry, a mistake tag "
    "used twice, mean R 0.5 below the baseline, more than twice the usual number of entries. "
    "A record of what was journaled, not a judgement of skill."
)


@router.get("/weekly", response_model=WeeklyReviewOut)
def journal_weekly(
    session: SessionDep,
    user_id: UserIdDep,
    book: BookOrAllQuery = None,
    source: Literal["paper", "imported", "replay", "all"] | None = None,
    week_end: date | None = None,
) -> WeeklyReviewOut:
    """A9.12 (M11.6): one week of closed entries, the baseline and what to look at."""
    from stockviz._time import utcnow
    from stockviz.services.journal.weekly import review

    chosen = parse_book(book)
    filters = edge.EdgeFilters(book_id=chosen if isinstance(chosen, int) else None, source=source)
    if filters.book_id is not None:
        resolve_book(session, user_id, filters.book_id)
    kept = [o for o in edge.collect_outcomes(session, user_id).outcomes if edge._keep(o, filters)]
    r = review(kept, week_end or utcnow().date())
    return WeeklyReviewOut(
        week_start=r.week_start,
        week_end=r.week_end,
        week=WeekFiguresOut(**r.week.__dict__),
        baseline_weeks=r.baseline_weeks,
        baseline_entries_per_week=r.baseline_entries_per_week,
        baseline_mean_r=r.baseline_mean_r,
        baseline_adherence=r.baseline_adherence,
        look_at=[LookAtOut(key=i.key, text=i.text, entry_ids=list(i.entry_ids)) for i in r.look_at],
        notes=r.notes,
        method=WEEKLY_METHOD,
    )
