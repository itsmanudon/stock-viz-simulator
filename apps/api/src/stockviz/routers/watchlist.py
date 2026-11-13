"""`/v1/watchlist` — per-user ticker watchlist.

Each user has a single default watchlist (auto-created on first read or write).
Items reference rows in ``symbols``; the GET response joins to symbol metadata
and the latest 1d close so the UI can render without extra round-trips.

Like the other ``/v1`` mutating routes, every endpoint depends on
``UserIdDep`` so the caller must present a valid signed JWT.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, col, select

from stockviz.auth import UserIdDep
from stockviz.db import get_session
from stockviz.models import Symbol, Watchlist, WatchlistItem
from stockviz.schemas import WatchlistItemOut
from stockviz.services.instruments import instrument_of
from stockviz.services.recent_bars import recent_bars

router = APIRouter(prefix="/v1/watchlist", tags=["watchlist"])

SessionDep = Annotated[Session, Depends(get_session)]


def _ensure_default_watchlist(session: Session, user_id: int) -> Watchlist:
    existing = session.exec(
        select(Watchlist).where(Watchlist.user_id == user_id).order_by(Watchlist.id)  # type: ignore[arg-type]
    ).first()
    if existing is not None:
        return existing
    wl = Watchlist(user_id=user_id, name="Default")
    session.add(wl)
    session.commit()
    session.refresh(wl)
    return wl


SPARKLINE_BARS = 30


def _item_out(
    item: WatchlistItem, symbol: Symbol, bars: list[tuple[datetime, Decimal]]
) -> WatchlistItemOut:
    """One row: the latest close, its date, and the last 30 closes (RS-12)."""
    last = bars[-1] if bars else None
    return WatchlistItemOut(
        ticker=item.ticker,
        name=symbol.name,
        sector=symbol.sector,
        added_at=item.added_at,
        last_close=last[1] if last else None,
        last_close_at=last[0] if last else None,
        currency=symbol.currency or "USD",
        closes=[close for _ts, close in bars],
    )


def _items_out(
    session: Session, rows: list[tuple[WatchlistItem, Symbol]]
) -> list[WatchlistItemOut]:
    """Every row from one batched bars query (audit RS-12: it was one per item)."""
    bars = recent_bars(
        session, [item.ticker for item, _sym in rows], limit_per_ticker=SPARKLINE_BARS
    )
    return [_item_out(item, sym, bars.get(item.ticker, [])) for item, sym in rows]


@router.get("", response_model=list[WatchlistItemOut])
def list_watchlist(session: SessionDep, user_id: UserIdDep) -> list[WatchlistItemOut]:
    wl = _ensure_default_watchlist(session, user_id)
    rows = list(
        session.exec(
            select(WatchlistItem, Symbol)
            .where(WatchlistItem.watchlist_id == wl.id)  # type: ignore[arg-type]
            .join(Symbol, Symbol.ticker == WatchlistItem.ticker)  # type: ignore[arg-type]
            .order_by(WatchlistItem.added_at.desc())  # type: ignore[attr-defined]
        )
    )
    return _items_out(session, rows)


def _item(session: Session, watchlist_id: int | None, ticker: str) -> WatchlistItem | None:
    """A watchlist row by public ticker (keyed by instrument since Phase 4.6b)."""
    return session.exec(
        select(WatchlistItem).where(
            col(WatchlistItem.watchlist_id) == watchlist_id,
            col(WatchlistItem.instrument_id) == instrument_of(ticker),
        )
    ).first()


@router.post("/{ticker}", response_model=WatchlistItemOut, status_code=status.HTTP_201_CREATED)
def add_watchlist_item(ticker: str, session: SessionDep, user_id: UserIdDep) -> WatchlistItemOut:
    ticker = ticker.upper()
    symbol = session.get(Symbol, ticker)
    if symbol is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Symbol {ticker!r} not found")

    wl = _ensure_default_watchlist(session, user_id)
    existing = _item(session, wl.id, ticker)
    if existing is None:
        existing = WatchlistItem(watchlist_id=wl.id, ticker=ticker)  # type: ignore[arg-type]
        session.add(existing)
        session.commit()
        session.refresh(existing)
    return _items_out(session, [(existing, symbol)])[0]


@router.delete("/{ticker}", status_code=status.HTTP_204_NO_CONTENT)
def remove_watchlist_item(ticker: str, session: SessionDep, user_id: UserIdDep) -> None:
    ticker = ticker.upper()
    wl = _ensure_default_watchlist(session, user_id)
    item = _item(session, wl.id, ticker)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{ticker!r} is not on the watchlist")
    session.delete(item)
    session.commit()
