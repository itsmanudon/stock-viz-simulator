"""The book's FY capital gains estimate and harvesting view (A7.12, M10.7).

Reads one INR book's trades in Indian listings (NSE/BSE), dated by the venue
day (IST), every year back to the first, so FIFO lots carry their real buy
dates. The FMV on 31 Jan 2018 for grandfathering is the stored daily high that
day (the rule's "highest price quoted"); prices are the book's own basis
(split-adjusted after a split, like the stored bars).

Harvesting lists open lots at the latest stored close with their term, the
days until they turn long term, and the unrealised gain or loss; it states
what realising them would do to this FY's figures, never what to do.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlmodel import Session, col, select

from stockviz.models import PriceBar
from stockviz.models.portfolio import Portfolio, Trade
from stockviz.services.markets.calendar import venue_for_ticker, venue_zone
from stockviz.services.tax.lots import (
    ZERO,
    Fill,
    FyComputation,
    LotBook,
    build_lots,
    compute_fy,
)
from stockviz.services.tax.rules import (
    FY_RULES,
    GRANDFATHER_FMV_DATE,
    FyRules,
    is_long_term,
)

INDIAN_VENUES = {"XNSE", "XBOM"}


class TaxNotAvailable(ValueError):
    """The book or year is outside what the estimate covers (409 or 400)."""


@dataclass(frozen=True)
class OpenLotView:
    ticker: str
    bought: date
    quantity: Decimal
    cost: Decimal
    close: Decimal | None
    close_date: date | None
    unrealised: Decimal | None
    term: str
    long_term_on: date


@dataclass(frozen=True)
class TaxReport:
    rules: FyRules
    book: LotBook
    fy: FyComputation
    open_lots: list[OpenLotView]
    as_of: date
    skipped_tickers: list[str]


def _venue_day(ts: datetime, ticker: str) -> date:
    zone = venue_zone(venue_for_ticker(ticker))
    return ts.replace(tzinfo=UTC).astimezone(zone).date()


def _anniversary(bought: date, months: int) -> date:
    """The first day the lot counts as long term (the day after the anniversary)."""
    day = bought
    while not is_long_term(bought, day, months):
        day += timedelta(days=1)
        if (day - bought).days > 800:
            break
    return day


def _fmv_2018(session: Session, tickers: list[str]) -> dict[str, Decimal]:
    start = datetime.combine(GRANDFATHER_FMV_DATE, datetime.min.time())
    rows = session.exec(
        select(col(PriceBar.ticker), col(PriceBar.high)).where(
            col(PriceBar.ticker).in_(tickers),
            col(PriceBar.interval) == "1d",
            col(PriceBar.ts) >= start,
            col(PriceBar.ts) < start + timedelta(days=1),
        )
    ).all()
    return {t: Decimal(h) for t, h in rows}


def _latest_closes(session: Session, tickers: list[str]) -> dict[str, tuple[date, Decimal]]:
    out: dict[str, tuple[date, Decimal]] = {}
    for t in tickers:
        row = session.exec(
            select(col(PriceBar.ts), col(PriceBar.close))
            .where(col(PriceBar.ticker) == t, col(PriceBar.interval) == "1d")
            .order_by(col(PriceBar.ts).desc())
            .limit(1)
        ).first()
        if row is not None:
            out[t] = (row[0].date(), Decimal(row[1]))
    return out


def build_report(
    session: Session,
    book: Portfolio,
    fy: str,
    *,
    surcharge_rate: Decimal = ZERO,
    today: date | None = None,
) -> TaxReport:
    rules = FY_RULES.get(fy)
    if rules is None:
        raise TaxNotAvailable(f"covers FY {', '.join(FY_RULES)} only")
    if book.base_currency != "INR":
        raise TaxNotAvailable("the India estimate covers INR books only")
    trades = session.exec(
        select(Trade).where(Trade.portfolio_id == book.id).order_by(col(Trade.ts), col(Trade.id))
    ).all()
    fills: list[Fill] = []
    skipped: set[str] = set()
    for i, t in enumerate(trades):
        if venue_for_ticker(t.ticker) not in INDIAN_VENUES:
            skipped.add(t.ticker)
            continue
        fills.append(
            Fill(
                t.ticker,
                _venue_day(t.ts, t.ticker),
                str(t.side).split(".")[-1].lower(),
                Decimal(t.quantity),
                Decimal(t.price),
                i,
            )
        )
    tickers = sorted({f.ticker for f in fills})
    lots = build_lots(fills, _fmv_2018(session, tickers))
    computed = compute_fy(lots.realised, lots.intraday, rules, surcharge_rate=surcharge_rate)
    closes = _latest_closes(session, sorted({lot.ticker for lot in lots.open_lots}))
    as_of = today or date.today()
    views: list[OpenLotView] = []
    for lot in lots.open_lots:
        close = closes.get(lot.ticker)
        cost = (lot.quantity * lot.price).quantize(Decimal("0.01"))
        value = (lot.quantity * close[1]).quantize(Decimal("0.01")) if close else None
        views.append(
            OpenLotView(
                ticker=lot.ticker,
                bought=lot.bought,
                quantity=lot.quantity,
                cost=cost,
                close=close[1] if close else None,
                close_date=close[0] if close else None,
                unrealised=(value - cost) if value is not None else None,
                term="long" if is_long_term(lot.bought, as_of) else "short",
                long_term_on=_anniversary(lot.bought, rules.long_term_after_months),
            )
        )
    return TaxReport(rules, lots, computed, views, as_of, sorted(skipped))
