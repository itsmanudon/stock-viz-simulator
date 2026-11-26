"""`/v1/journal/entries` (A5.5, M10.3): round trips across paper, imported and replay.

Authed, private to the owner; another user's entry is 404.

- ``GET ""``: your entries, newest first. ``?book=<id>`` keeps one book's
  (another user's book 404); omitted or ``all`` lists every book and your
  replay sessions (anonymised drills not yet revealed are left out).
  Filters: ``status`` open|closed, ``source`` paper|imported|replay,
  ``setup_version_id`` (the plan's), ``tag`` (setup or mistake tag,
  ignoring case), ``ticker``, ``from``/``to`` (the entry's venue date).
- ``GET /{id}``: the entry with its fills, plan adherence and news at entry
  and exit.
- ``PATCH /{id}``: the user's text (review notes, mistakes, lessons, setup
  and mistake tags). Figures are never written: they are computed on read.

Rules: ``services/journal/entries.py`` and ``roundtrips.py``.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session

from stockviz.auth import UserIdDep
from stockviz.db import get_session
from stockviz.routers.book_query import BookOrAllQuery, parse_book
from stockviz.schemas import JournalEntriesOut, JournalEntryOut, JournalEntryPatch
from stockviz.services.journal import entries as svc

router = APIRouter(prefix="/v1/journal/entries", tags=["journal"])

SessionDep = Annotated[Session, Depends(get_session)]


def _not_found(exc: svc.JournalEntryNotFound) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))


@router.get("", response_model=JournalEntriesOut)
def list_journal_entries(
    session: SessionDep,
    user_id: UserIdDep,
    book: BookOrAllQuery = None,
    status_: Annotated[Literal["open", "closed"] | None, Query(alias="status")] = None,
    source: Literal["paper", "imported", "replay"] | None = None,
    setup_version_id: Annotated[int | None, Query(ge=1)] = None,
    tag: Annotated[str | None, Query(min_length=1, max_length=32)] = None,
    ticker: Annotated[str | None, Query(min_length=1, max_length=16)] = None,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JournalEntriesOut:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "`from` is after `to`")
    chosen = parse_book(book)
    filters = svc.Filters(
        book_id=chosen if isinstance(chosen, int) else None,
        status=status_,
        source=source,
        setup_version_id=setup_version_id,
        tag=tag,
        ticker=ticker,
        date_from=date_from,
        date_to=date_to,
    )
    rows, total = svc.list_entries(session, user_id, filters, limit=limit, offset=offset)
    return JournalEntriesOut(
        entries=rows, total=total, limit=limit, offset=offset, note=svc.LIST_NOTE
    )


@router.get("/{entry_id}", response_model=JournalEntryOut)
def get_journal_entry(entry_id: int, session: SessionDep, user_id: UserIdDep) -> JournalEntryOut:
    try:
        return svc.get_entry(session, user_id, entry_id)
    except svc.JournalEntryNotFound as exc:
        raise _not_found(exc) from exc


@router.patch("/{entry_id}", response_model=JournalEntryOut)
def patch_journal_entry(
    entry_id: int, body: JournalEntryPatch, session: SessionDep, user_id: UserIdDep
) -> JournalEntryOut:
    try:
        return svc.patch_entry(session, user_id, entry_id, body)
    except svc.JournalEntryNotFound as exc:
        raise _not_found(exc) from exc
    except svc.JournalEntryError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
