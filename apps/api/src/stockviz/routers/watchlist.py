"""`/v1/watchlist` — the user's **default** list (deprecated since A2.5).

Kept so older clients keep working: every route acts on the default list
(``services/watchlists.ensure_default``), which is made on first use. New
code uses ``/v1/watchlists`` (``routers/watchlists.py``), which also serves
the other lists, notes, tags and column sets. Response shapes are unchanged.

Like the other ``/v1`` mutating routes, every endpoint depends on
``UserIdDep`` so the caller must present a valid signed JWT.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from stockviz.auth import UserIdDep
from stockviz.db import get_session
from stockviz.models import Symbol, WatchlistItem
from stockviz.schemas import WatchlistItemOut
from stockviz.services import watchlists as svc

router = APIRouter(prefix="/v1/watchlist", tags=["watchlist"])

SessionDep = Annotated[Session, Depends(get_session)]

SPARKLINE_BARS = svc.SPARKLINE_BARS


def item_fields(item: WatchlistItem, symbol: Symbol, bars: list[tuple[datetime, Decimal]]) -> dict:
    """One row: the latest close, its date, and the last 30 closes (RS-12)."""
    last = bars[-1] if bars else None
    return {
        "ticker": item.ticker,
        "name": symbol.name,
        "sector": symbol.sector,
        "added_at": item.added_at,
        "last_close": last[1] if last else None,
        "last_close_at": last[0] if last else None,
        "currency": symbol.currency or "USD",
        "closes": [close for _ts, close in bars],
    }


def _items_out(
    session: Session, rows: list[tuple[WatchlistItem, Symbol]]
) -> list[WatchlistItemOut]:
    """Every row from one batched bars query (audit RS-12: it was one per item)."""
    bars = svc.sparkline_bars(session, [item.ticker for item, _sym in rows])
    return [
        WatchlistItemOut(**item_fields(item, sym, bars.get(item.ticker, []))) for item, sym in rows
    ]


@router.get("", response_model=list[WatchlistItemOut], deprecated=True)
def list_watchlist(session: SessionDep, user_id: UserIdDep) -> list[WatchlistItemOut]:
    wl = svc.ensure_default(session, user_id)
    assert wl.id is not None
    return _items_out(session, svc.item_rows(session, wl.id))


@router.post(
    "/{ticker}",
    response_model=WatchlistItemOut,
    status_code=status.HTTP_201_CREATED,
    deprecated=True,
)
def add_watchlist_item(ticker: str, session: SessionDep, user_id: UserIdDep) -> WatchlistItemOut:
    ticker = ticker.upper()
    symbol = session.get(Symbol, ticker)
    if symbol is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Symbol {ticker!r} not found")
    wl = svc.ensure_default(session, user_id)
    existing = svc.find_item(session, wl.id, ticker)
    if existing is None:
        svc.add_items(session, wl, [ticker])
        existing = svc.find_item(session, wl.id, ticker)
        assert existing is not None
    return _items_out(session, [(existing, symbol)])[0]


@router.delete("/{ticker}", status_code=status.HTTP_204_NO_CONTENT, deprecated=True)
def remove_watchlist_item(ticker: str, session: SessionDep, user_id: UserIdDep) -> None:
    wl = svc.ensure_default(session, user_id)
    svc.remove_item(session, wl, ticker)
