"""The morning brief (A9.12, M11.6): what changed overnight for the symbols a
user holds or watches. Deterministic, read only, nothing stored.

- **Symbols:** positions in the user's books, then their watchlists' symbols,
  at most ``MAX_SYMBOLS``.
- **Moves:** each symbol's last stored daily close against the one before,
  with both dates (an end-of-day product: never "today's" move unless the
  bar is today's); the largest moves first, at most ``MAX_MOVES``.
- **Alerts:** the user's alert notifications of the last 24 hours.
- **Earnings:** stored earnings events for the symbols in the next 7 days.
- **Documents:** documents for the symbols that became public in the last 7
  days (A7.10).
- **Plans and orders:** counts of open or active plans and pending orders.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlmodel import Session, col, func, select

from stockviz._time import utcnow
from stockviz.models import (
    Document,
    EarningsEvent,
    Notification,
    PendingOrder,
    Portfolio,
    Position,
    PriceBar,
    TradePlan,
    Watchlist,
    WatchlistItem,
)
from stockviz.models.order import OrderStatus

MAX_SYMBOLS = 50
MAX_MOVES = 8
MAX_ITEMS = 10


@dataclass(frozen=True)
class Move:
    ticker: str
    close: Decimal
    close_date: date
    previous_close: Decimal
    previous_date: date
    change_pct: float
    held: bool


@dataclass
class Brief:
    generated_at: datetime
    symbols: list[str]
    moves: list[Move] = field(default_factory=list)
    alerts: list[Notification] = field(default_factory=list)
    earnings: list[EarningsEvent] = field(default_factory=list)
    documents: list[tuple[Document, str]] = field(default_factory=list)
    open_plans: int = 0
    pending_orders: int = 0


def user_symbols(session: Session, user_id: int) -> tuple[list[str], set[str]]:
    books = select(Portfolio.id).where(col(Portfolio.user_id) == user_id)
    held = list(
        session.exec(
            select(Position.ticker).where(col(Position.portfolio_id).in_(books)).distinct()
        ).all()
    )
    lists = select(Watchlist.id).where(col(Watchlist.user_id) == user_id)
    watched = session.exec(
        select(WatchlistItem.ticker).where(col(WatchlistItem.watchlist_id).in_(lists)).distinct()
    ).all()
    ordered = list(dict.fromkeys(sorted(held) + sorted(watched)))[:MAX_SYMBOLS]
    return ordered, set(held)


def _move(session: Session, ticker: str, held: bool) -> Move | None:
    bars = session.exec(
        select(PriceBar)
        .where(col(PriceBar.ticker) == ticker, col(PriceBar.interval) == "1d")
        .order_by(col(PriceBar.ts).desc())
        .limit(2)
    ).all()
    if len(bars) < 2 or not bars[1].close:
        return None
    ts, close, pts, pclose = bars[0].ts, bars[0].close, bars[1].ts, bars[1].close
    pct = float((close - pclose) / pclose * 100)
    return Move(ticker, close, ts.date(), pclose, pts.date(), round(pct, 2), held)


def morning_brief(session: Session, user_id: int, *, now: datetime | None = None) -> Brief:
    at = now or utcnow()
    symbols, held = user_symbols(session, user_id)
    out = Brief(generated_at=at, symbols=symbols)
    moves = [m for t in symbols if (m := _move(session, t, t in held)) is not None]
    out.moves = sorted(moves, key=lambda m: (-abs(m.change_pct), m.ticker))[:MAX_MOVES]
    out.alerts = list(
        session.exec(
            select(Notification)
            .where(
                col(Notification.user_id) == user_id,
                col(Notification.category) == "alert",
                col(Notification.created_at) >= at - timedelta(hours=24),
            )
            .order_by(col(Notification.created_at).desc())
            .limit(MAX_ITEMS)
        ).all()
    )
    if symbols:
        today = at.date()
        out.earnings = list(
            session.exec(
                select(EarningsEvent)
                .where(
                    col(EarningsEvent.ticker).in_(symbols),
                    col(EarningsEvent.event_date) >= today,
                    col(EarningsEvent.event_date) <= today + timedelta(days=7),
                )
                .order_by(col(EarningsEvent.event_date), col(EarningsEvent.ticker))
                .limit(MAX_ITEMS)
            ).all()
        )
        from stockviz.services.instruments import instrument_ids

        ids = instrument_ids(session, symbols)
        by_id = {v: k for k, v in ids.items()}
        if by_id:
            docs = session.exec(
                select(Document)
                .where(
                    col(Document.instrument_id).in_(list(by_id)),
                    col(Document.available_at) <= at,
                    col(Document.available_at) >= at - timedelta(days=7),
                )
                .order_by(col(Document.available_at).desc())
                .limit(MAX_ITEMS)
            ).all()
            out.documents = [(d, by_id[d.instrument_id]) for d in docs]
    out.open_plans = session.exec(
        select(func.count())
        .select_from(TradePlan)
        .where(col(TradePlan.user_id) == user_id, col(TradePlan.status).in_(["open", "active"]))
    ).one()
    books = select(Portfolio.id).where(col(Portfolio.user_id) == user_id)
    out.pending_orders = session.exec(
        select(func.count())
        .select_from(PendingOrder)
        .where(
            col(PendingOrder.portfolio_id).in_(books),
            col(PendingOrder.status) == OrderStatus.PENDING,
        )
    ).one()
    return out
