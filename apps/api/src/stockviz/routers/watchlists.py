"""`/v1/watchlists` (A2.5, M4.6): many lists, notes, tags, column values. Authed.

- ``GET ""`` (``?contains=TICKER`` adds ``contains`` per list): the caller's
  lists by position; the default list is made on first use.
- ``POST ""`` ``{name, colour}``: 201. ``PATCH /{id}``: name, colour,
  ``is_default: true``, ``column_set_id`` (null clears). ``POST /reorder``
  ``{ids}``: every list id once. ``DELETE /{id}``: 204; the default flag moves
  to the first remaining list, and deleting the last list leaves an empty
  "Default".
- ``GET /{id}/items?column_set_id=&columns=a,b``: the rows (sparkline closes
  as on ``/v1/watchlist``), notes, tags and the chosen columns' values.
- ``POST /{id}/items`` ``{tickers}``: bulk add (up to 100, de-duplicated);
  ``{added, already_listed, unknown, item_count}``.
- ``PATCH /{id}/items/{ticker}`` ``{note?, tags?}``; ``DELETE`` removes.

Another user's list or column set is 404. Rules are in
``services/watchlists.py``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlmodel import Session

from stockviz.auth import UserIdDep
from stockviz.db import get_session
from stockviz.models import Watchlist
from stockviz.routers.watchlist import item_fields
from stockviz.schemas import (
    WatchlistBulkIn,
    WatchlistBulkOut,
    WatchlistIn,
    WatchlistItemPatch,
    WatchlistItemsOut,
    WatchlistOrderIn,
    WatchlistOut,
    WatchlistPatch,
    WatchlistRowOut,
)
from stockviz.services import watchlists as svc

router = APIRouter(prefix="/v1/watchlists", tags=["watchlists"])

SessionDep = Annotated[Session, Depends(get_session)]


def _out(wl: Watchlist, count: int, contains: bool | None = None) -> WatchlistOut:
    assert wl.id is not None
    return WatchlistOut(
        id=wl.id,
        name=wl.name,
        colour=wl.colour,  # type: ignore[arg-type]
        position=wl.position,
        is_default=wl.is_default,
        column_set_id=wl.column_set_id,
        item_count=count,
        contains=contains,
        created_at=wl.created_at,
    )


def _one(session: Session, wl: Watchlist) -> WatchlistOut:
    assert wl.id is not None
    return _out(wl, svc.item_counts(session, [wl.id]).get(wl.id, 0))


def _all(session: Session, user_id: int, contains: str | None = None) -> list[WatchlistOut]:
    svc.ensure_default(session, user_id)
    lists = svc.lists_of(session, user_id)
    counts = svc.item_counts(session, [w.id for w in lists if w.id is not None])
    holding = svc.lists_containing(session, user_id, contains) if contains else None
    return [
        _out(w, counts.get(w.id or 0, 0), None if holding is None else w.id in holding)
        for w in lists
    ]


@router.get("", response_model=list[WatchlistOut])
def list_watchlists(
    session: SessionDep,
    user_id: UserIdDep,
    contains: Annotated[str | None, Query(max_length=16)] = None,
) -> list[WatchlistOut]:
    return _all(session, user_id, contains)


@router.post("", response_model=WatchlistOut, status_code=status.HTTP_201_CREATED)
def create_watchlist(body: WatchlistIn, session: SessionDep, user_id: UserIdDep) -> WatchlistOut:
    return _one(session, svc.create_list(session, user_id, body.name, body.colour))


@router.post("/reorder", response_model=list[WatchlistOut])
def reorder_watchlists(
    body: WatchlistOrderIn, session: SessionDep, user_id: UserIdDep
) -> list[WatchlistOut]:
    svc.reorder_lists(session, user_id, body.ids)
    return _all(session, user_id)


@router.patch("/{watchlist_id}", response_model=WatchlistOut)
def update_watchlist(
    watchlist_id: int, body: WatchlistPatch, session: SessionDep, user_id: UserIdDep
) -> WatchlistOut:
    wl = svc.update_list(session, user_id, watchlist_id, fields=body.model_dump(exclude_unset=True))
    return _one(session, wl)


@router.delete("/{watchlist_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_watchlist(watchlist_id: int, session: SessionDep, user_id: UserIdDep) -> None:
    svc.delete_list(session, user_id, watchlist_id)


@router.get("/{watchlist_id}/items", response_model=WatchlistItemsOut)
def list_items(
    watchlist_id: int,
    session: SessionDep,
    user_id: UserIdDep,
    column_set_id: int | None = None,
    columns: Annotated[str | None, Query(max_length=400)] = None,
) -> WatchlistItemsOut:
    wl = svc.get_list(session, user_id, watchlist_id)
    keys, set_id = svc.resolve_columns(
        session, user_id, wl, column_set_id=column_set_id, columns=columns
    )
    rows = svc.item_rows(session, watchlist_id)
    bars = svc.sparkline_bars(session, [item.ticker for item, _sym in rows])
    values = svc.column_values(session, rows, keys, bars)
    items = [
        WatchlistRowOut(
            **item_fields(item, sym, bars.get(item.ticker, [])),
            note=item.note,
            tags=list(item.tags or []),
            values=values.get(item.ticker, {}),
        )
        for item, sym in rows
    ]
    return WatchlistItemsOut(
        watchlist=_out(wl, len(rows)),
        columns=keys,  # type: ignore[arg-type]
        column_set_id=set_id,
        items=items,
    )


@router.post("/{watchlist_id}/items", response_model=WatchlistBulkOut)
def add_items(
    watchlist_id: int, body: WatchlistBulkIn, session: SessionDep, user_id: UserIdDep
) -> WatchlistBulkOut:
    wl = svc.get_list(session, user_id, watchlist_id)
    result = svc.add_items(session, wl, body.tickers)
    return WatchlistBulkOut(
        added=result.added,
        already_listed=result.already_listed,
        unknown=result.unknown,
        item_count=result.item_count,
    )


@router.patch("/{watchlist_id}/items/{ticker}", response_model=WatchlistRowOut)
def update_item(
    watchlist_id: int,
    ticker: str,
    body: WatchlistItemPatch,
    session: SessionDep,
    user_id: UserIdDep,
) -> WatchlistRowOut:
    wl = svc.get_list(session, user_id, watchlist_id)
    item, sym = svc.update_item(session, wl, ticker, fields=body.model_dump(exclude_unset=True))
    bars = svc.sparkline_bars(session, [item.ticker])
    return WatchlistRowOut(
        **item_fields(item, sym, bars.get(item.ticker, [])),
        note=item.note,
        tags=list(item.tags or []),
    )


@router.delete("/{watchlist_id}/items/{ticker}", status_code=status.HTTP_204_NO_CONTENT)
def remove_item(watchlist_id: int, ticker: str, session: SessionDep, user_id: UserIdDep) -> None:
    wl = svc.get_list(session, user_id, watchlist_id)
    svc.remove_item(session, wl, ticker)
