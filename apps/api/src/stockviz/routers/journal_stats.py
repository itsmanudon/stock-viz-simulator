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
from stockviz.schemas import EdgeStatsOut
from stockviz.services.journal import edge

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
