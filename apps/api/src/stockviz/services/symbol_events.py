"""One merged, typed list of a symbol's chart events (A3.5, M2.8).

Types: ``news`` (Aegis documents linked to the symbol, clustered by day),
``earnings`` (``earnings_events``), ``dividend`` (ex-dates, ``dividends``),
``split`` (``corporate_actions`` of kind ``split``) and ``fill`` (the
caller's own trades on the symbol; only with a verified user id).

**News clusters.** A document belongs to the UTC date of its
``available_at`` (the field ``/v1/symbols/{t}/news`` orders by; never
``published_at``). One cluster per date: the count of linked documents that
day, the distinct source names, and up to ``NEWS_ITEMS_PER_DAY`` headlines
(title, source, URL, times). No article text: StockViz stores none.

**Fills.** Read only for ``user_id``: trades of that user's portfolio on the
symbol's instrument. ``r_multiple`` is null until A5 adds trade plans.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlmodel import Session, col, select

from stockviz.models import (
    AegisDocument,
    AegisDocumentEntity,
    AegisMapping,
    CorporateAction,
    Dividend,
    EarningsEvent,
    Portfolio,
    Symbol,
    Trade,
)
from stockviz.models.corporate_action import SPLIT
from stockviz.services.aegis.read import STOCKVIZ_SCHEME, stockviz_identifier
from stockviz.services.instruments import instrument_of

EVENT_TYPES: tuple[str, ...] = ("news", "earnings", "dividend", "split", "fill")
PUBLIC_TYPES: tuple[str, ...] = ("news", "earnings", "dividend", "split")
NEWS_ITEMS_PER_DAY = 20
MAX_NEWS_DOCUMENTS = 5000
MAX_FILLS = 2000


@dataclass(frozen=True)
class NewsHeadline:
    id: str
    title: str
    source: str | None
    url: str | None
    available_at: datetime
    published_at: datetime | None


@dataclass
class SymbolEvent:
    type: str
    date: date
    # news
    count: int | None = None
    sources: list[str] = field(default_factory=list)
    headlines: list[NewsHeadline] = field(default_factory=list)
    # earnings
    report_time: str | None = None
    fiscal_period: str | None = None
    eps_estimate: Decimal | None = None
    eps_actual: Decimal | None = None
    surprise_pct: Decimal | None = None
    # dividend
    amount: Decimal | None = None
    currency: str | None = None
    # split
    ratio_from: Decimal | None = None
    ratio_to: Decimal | None = None
    # fill
    ts: datetime | None = None
    side: str | None = None
    quantity: Decimal | None = None
    price: Decimal | None = None
    r_multiple: float | None = None
    book_id: int | None = None


def _day_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    return datetime.combine(start, time.min), datetime.combine(end + timedelta(days=1), time.min)


def news_clusters(
    session: Session,
    ticker: str,
    start: date,
    end: date,
    *,
    available_until: datetime | None = None,
) -> list[SymbolEvent]:
    """``available_until`` (A4.6, replay): also keep only documents whose
    ``available_at`` is at or before that instant (naive UTC)."""
    lo, hi = _day_bounds(start, end)
    cap = [col(AegisDocument.available_at) <= available_until] if available_until else []
    linked = (
        select(AegisDocumentEntity.document_id)
        .join(AegisMapping, col(AegisMapping.entity_id) == col(AegisDocumentEntity.entity_id))
        .where(
            AegisMapping.scheme == STOCKVIZ_SCHEME,
            AegisMapping.identifier == stockviz_identifier(ticker),
        )
    )
    docs = session.exec(
        select(AegisDocument)
        .where(
            col(AegisDocument.document_id).in_(linked),
            col(AegisDocument.available_at) >= lo,
            col(AegisDocument.available_at) < hi,
            *cap,
        )
        .order_by(col(AegisDocument.available_at).desc(), col(AegisDocument.document_id))
        .limit(MAX_NEWS_DOCUMENTS)
    ).all()
    by_day: dict[date, SymbolEvent] = {}
    for doc in docs:
        day = doc.available_at.date()
        event = by_day.setdefault(day, SymbolEvent(type="news", date=day, count=0))
        event.count = (event.count or 0) + 1
        if doc.source_name and doc.source_name not in event.sources:
            event.sources.append(doc.source_name)
        if len(event.headlines) < NEWS_ITEMS_PER_DAY:
            event.headlines.append(
                NewsHeadline(
                    id=doc.document_id,
                    title=doc.title,
                    source=doc.source_name,
                    url=doc.url,
                    available_at=doc.available_at,
                    published_at=doc.published_at,
                )
            )
    for event in by_day.values():
        event.sources.sort()
    return list(by_day.values())


def _earnings(session: Session, ticker: str, start: date, end: date) -> list[SymbolEvent]:
    rows = session.exec(
        select(EarningsEvent).where(
            EarningsEvent.instrument_id == instrument_of(ticker),
            col(EarningsEvent.event_date) >= start,
            col(EarningsEvent.event_date) <= end,
        )
    ).all()
    return [
        SymbolEvent(
            type="earnings",
            date=r.event_date,
            report_time=r.report_time,
            fiscal_period=r.fiscal_period or None,
            eps_estimate=r.eps_estimate,
            eps_actual=r.eps_actual,
            surprise_pct=r.surprise_pct,
        )
        for r in rows
    ]


def _dividends(
    session: Session, ticker: str, start: date, end: date, currency: str
) -> list[SymbolEvent]:
    rows = session.exec(
        select(Dividend).where(
            Dividend.instrument_id == instrument_of(ticker),
            col(Dividend.ex_date) >= start,
            col(Dividend.ex_date) <= end,
        )
    ).all()
    return [
        SymbolEvent(type="dividend", date=r.ex_date, amount=r.amount, currency=currency)
        for r in rows
    ]


def _splits(session: Session, ticker: str, start: date, end: date) -> list[SymbolEvent]:
    rows = session.exec(
        select(CorporateAction).where(
            CorporateAction.instrument_id == instrument_of(ticker),
            CorporateAction.kind == SPLIT,
            col(CorporateAction.ex_date) >= start,
            col(CorporateAction.ex_date) <= end,
        )
    ).all()
    return [
        SymbolEvent(type="split", date=r.ex_date, ratio_from=r.ratio_from, ratio_to=r.ratio_to)
        for r in rows
    ]


def _fills(
    session: Session,
    ticker: str,
    start: date,
    end: date,
    user_id: int,
    book_id: int | None = None,
) -> list[SymbolEvent]:
    """The caller's fills across all their books (A5.1), or one book's."""
    lo, hi = _day_bounds(start, end)
    stmt = (
        select(Trade)
        .join(Portfolio, col(Portfolio.id) == col(Trade.portfolio_id))
        .where(
            Portfolio.user_id == user_id,
            Trade.instrument_id == instrument_of(ticker),
            col(Trade.ts) >= lo,
            col(Trade.ts) < hi,
        )
    )
    if book_id is not None:
        stmt = stmt.where(col(Trade.portfolio_id) == book_id)
    rows = session.exec(stmt.order_by(col(Trade.ts)).limit(MAX_FILLS)).all()
    return [
        SymbolEvent(
            type="fill",
            date=r.ts.date(),
            ts=r.ts,
            side=str(getattr(r.side, "value", r.side)),
            quantity=r.quantity,
            price=r.price,
            r_multiple=None,
            book_id=r.portfolio_id,
        )
        for r in rows
    ]


def symbol_events(
    session: Session,
    ticker: str,
    *,
    start: date,
    end: date,
    types: tuple[str, ...],
    user_id: int | None,
    book_id: int | None = None,
) -> list[SymbolEvent]:
    """Every wanted event in [start, end], oldest first, then in type order."""
    symbol = session.get(Symbol, ticker)
    currency = symbol.currency if symbol else "USD"
    out: list[SymbolEvent] = []
    if "news" in types:
        out += news_clusters(session, ticker, start, end)
    if "earnings" in types:
        out += _earnings(session, ticker, start, end)
    if "dividend" in types:
        out += _dividends(session, ticker, start, end, currency)
    if "split" in types:
        out += _splits(session, ticker, start, end)
    if "fill" in types and user_id is not None:
        out += _fills(session, ticker, start, end, user_id, book_id)
    order = {t: i for i, t in enumerate(EVENT_TYPES)}
    out.sort(key=lambda e: (e.date, order[e.type], e.ts or datetime.min))
    return out
