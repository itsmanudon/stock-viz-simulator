"""`/v1/watchlist` — per-user ticker watchlist.

Each user has a single default watchlist (auto-created on first read or write).
Items reference rows in ``symbols``; the GET response joins to symbol metadata
and the latest 1d close so the UI can render without extra round-trips.

Like the other ``/v1`` mutating routes, every endpoint depends on
``UserIdDep`` so the caller must present a valid signed JWT.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from stockviz.auth import UserIdDep
from stockviz.db import get_session
from stockviz.models import PriceBar, Symbol, Watchlist, WatchlistItem
from stockviz.schemas import WatchlistItemOut

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


def _latest_close(session: Session, ticker: str):
    bar = session.exec(
        select(PriceBar)
        .where(PriceBar.ticker == ticker, PriceBar.interval == "1d")
        .order_by(PriceBar.ts.desc())  # type: ignore[attr-defined]
        .limit(1)
    ).first()
    return bar.close if bar else None


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
    return [
        WatchlistItemOut(
            ticker=item.ticker,
            name=sym.name,
            sector=sym.sector,
            added_at=item.added_at,
            last_close=_latest_close(session, item.ticker),
        )
        for item, sym in rows
    ]


@router.post("/{ticker}", response_model=WatchlistItemOut, status_code=status.HTTP_201_CREATED)
def add_watchlist_item(ticker: str, session: SessionDep, user_id: UserIdDep) -> WatchlistItemOut:
    ticker = ticker.upper()
    symbol = session.get(Symbol, ticker)
    if symbol is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Symbol {ticker!r} not found")

    wl = _ensure_default_watchlist(session, user_id)
    existing = session.get(WatchlistItem, (wl.id, ticker))
    if existing is None:
        existing = WatchlistItem(watchlist_id=wl.id, ticker=ticker)  # type: ignore[arg-type]
        session.add(existing)
        session.commit()
        session.refresh(existing)
    return WatchlistItemOut(
        ticker=existing.ticker,
        name=symbol.name,
        sector=symbol.sector,
        added_at=existing.added_at,
        last_close=_latest_close(session, existing.ticker),
    )


@router.delete("/{ticker}", status_code=status.HTTP_204_NO_CONTENT)
def remove_watchlist_item(ticker: str, session: SessionDep, user_id: UserIdDep) -> None:
    ticker = ticker.upper()
    wl = _ensure_default_watchlist(session, user_id)
    item = session.get(WatchlistItem, (wl.id, ticker))
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{ticker!r} is not on the watchlist")
    session.delete(item)
    session.commit()
