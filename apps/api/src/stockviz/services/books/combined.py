"""All books: one view across a user's books in the display currency (A5.2, M10.1).

The design note's combined rule ("Analytics per book and combined"):

- **NAV.** Each book's NAV points (its opening value, its nightly snapshots
  and, for the live figure, today's valuation) are in the book's base
  currency. Every point is converted into the user's display currency at the
  rate stored on or before that point's own date, then summed. A book's value
  on a date it has no point for is its last point before it (a missed night).
  A book adds nothing before it opened.
- **Returns.** TWR is chained over the summed series
  (``services/trading/returns.py::time_weighted_return``) with outside flows:
  a book's opening value on its opening date (a new book is new money, not a
  gain), and an imported book's buys (money in, cost plus fees) and sells
  (money out, proceeds less fees) at the trade date's rate. Transfers between
  books would net to nothing and none exist yet. XIRR takes the same flows
  with today's combined value as the last one.
- **FX age.** A rate is stale when it is older than the New York session
  before the point's own session: the fill rule of audit MD-7
  (``fx.fill_rate_floor``), which tolerates one missed night. A stale rate is
  used and warned about; a missing rate drops that date from the combined
  series (its flows move to the next date kept) and is warned about too. Never
  a silent zero.
- **Exposure, allocation, movers.** One valuation merged across books: the
  same ticker in two books is one holding (quantities summed, average cost
  weighted by quantity).
- **Per book only:** risk (VaR, Monte Carlo), stress, attribution, holding
  XIRRs, limits, dividends, options strategies and the journal. Their
  routes take a book id, never ``all``.
"""

from __future__ import annotations

import bisect
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from itertools import pairwise

from sqlmodel import Session, col, select

from stockviz.models import BookKind, FxRate, Portfolio, PortfolioSnapshot, Trade, TradeSide
from stockviz.services.markets.calendar import previous_session, session_on_or_before
from stockviz.services.trading.portfolio import (
    CurrencyCash,
    PortfolioPosition,
    PortfolioValuation,
    ValuationWarning,
    compute_portfolio,
)

ALL_BOOKS = "all"

COMBINED_TWR_BASIS = (
    "every book's NAV converted to the display currency at its date's rate and summed; "
    "chained, with a book's opening value and an imported book's buys and sells as "
    "outside flows"
)
COMBINED_XIRR_BASIS = (
    "each book's opening value and an imported book's buys and sells in the display "
    "currency at their date's rate, today's combined value as the last flow"
)
FX_STALE_RULE = (
    "a rate is stale when it is older than the New York session before the date it "
    "values (the fill rule, audit MD-7)"
)


def stale_floor(day: date) -> date:
    """The oldest rate date that may value ``day`` without a warning (MD-7)."""
    return previous_session(session_on_or_before(day))


@dataclass(frozen=True, slots=True)
class FxNote:
    """A conversion the combined figure could not make with a fresh rate."""

    currency: str
    day: date
    rate_date: date | None  # None: no rate on or before ``day`` at all


@dataclass(slots=True)
class RateBook:
    """USD-per-unit rates per currency, looked up on or before a date."""

    by_currency: dict[str, tuple[list[date], list[Decimal]]] = field(default_factory=dict)

    @classmethod
    def load(cls, session: Session, currencies: Iterable[str], *, until: date) -> RateBook:
        book = cls()
        for ccy in sorted(set(currencies) - {"USD"}):
            rows = session.exec(
                select(col(FxRate.date), col(FxRate.usd_rate))
                .where(FxRate.currency == ccy, col(FxRate.date) <= until)
                .order_by(col(FxRate.date))
            ).all()
            book.by_currency[ccy] = ([d for d, _ in rows], [r for _, r in rows])
        return book

    def usd_per(self, ccy: str, day: date) -> tuple[Decimal, date] | None:
        if ccy == "USD":
            return Decimal(1), day
        dates, rates = self.by_currency.get(ccy, ([], []))
        i = bisect.bisect_right(dates, day)
        if i == 0:
            return None
        return rates[i - 1], dates[i - 1]

    def convert(
        self, amount: Decimal, *, src: str, dst: str, day: date, notes: list[FxNote]
    ) -> Decimal | None:
        """``amount`` from ``src`` to ``dst`` at ``day``'s rate; None when one is missing.

        A stale or missing leg is appended to ``notes``.
        """
        if src == dst:
            return amount
        legs: list[Decimal] = []
        for ccy in (src, dst):
            found = self.usd_per(ccy, day)
            if found is None:
                notes.append(FxNote(ccy, day, None))
                return None
            rate, rate_day = found
            if ccy != "USD" and rate_day < stale_floor(day):
                notes.append(FxNote(ccy, day, rate_day))
            legs.append(rate)
        usd_per_src, usd_per_dst = legs
        if usd_per_dst == 0:
            return None
        return amount * usd_per_src / usd_per_dst


@dataclass(frozen=True, slots=True)
class BookSeries:
    """One book's NAV points and outside flows, in its base currency."""

    book_id: int
    currency: str
    opened: date
    points: list[tuple[date, Decimal]]
    flows: list[tuple[date, Decimal]] = field(default_factory=list)
    # The book's opening value (``opening_nav``): its money in on ``opened``.
    opening: Decimal = Decimal(0)


@dataclass(frozen=True, slots=True)
class CombinedSeries:
    """The summed series in the display currency, its flows and what it warns."""

    currency: str
    opened: date | None
    points: list[tuple[date, Decimal]]
    flows: list[tuple[date, Decimal]]
    notes: list[FxNote]

    @property
    def flow_by_day(self) -> dict[date, Decimal]:
        out: dict[date, Decimal] = defaultdict(Decimal)
        for day, amount in self.flows:
            out[day] += amount
        return dict(out)


def combine(
    series: Sequence[BookSeries],
    *,
    display: str,
    convert: Callable[[Decimal, str, date, list[FxNote]], Decimal | None],
) -> CombinedSeries:
    """Sum the books' series in ``display`` (pure but for ``convert``).

    ``convert(amount, currency, day, notes)`` turns a base amount into the
    display currency at ``day``'s rate (None when no rate exists). The first
    book to open sets the start; a later book's opening value is a flow on its
    opening date, so creating a book is never a return.
    """
    notes: list[FxNote] = []
    live = [s for s in series if s.points]
    if not live:
        return CombinedSeries(display, None, [], [], notes)
    start = min(s.opened for s in live)
    days = sorted({day for s in live for day, _ in s.points if day >= start})

    # Book flows: the opening of a book that opened after the start, then
    # the book's own (an imported book's buys and sells).
    raw_flows: list[tuple[date, str, Decimal]] = []
    for s in live:
        if s.opened > start and s.opening != 0:
            raw_flows.append((s.opened, s.currency, s.opening))
        raw_flows += [(d, s.currency, a) for d, a in s.flows if d > start]

    points: list[tuple[date, Decimal]] = []
    dropped: list[date] = []
    for day in days:
        total = Decimal(0)
        ok = True
        for s in live:
            if s.opened > day:
                continue
            value = _value_on(s.points, day)
            if value is None:
                continue
            converted = convert(value, s.currency, day, notes)
            if converted is None:
                ok = False
                break
            total += converted
        if ok:
            points.append((day, total))
        else:
            dropped.append(day)

    kept = [d for d, _ in points]
    flows: list[tuple[date, Decimal]] = []
    for day, ccy, amount in raw_flows:
        # A flow on a dropped date counts on the next date kept, at its rate.
        i = bisect.bisect_left(kept, day)
        if i == len(kept):
            continue
        converted = convert(amount, ccy, kept[i], notes)
        if converted is not None:
            flows.append((kept[i], converted))
    return CombinedSeries(display, start, points, flows, _dedupe(notes))


def _value_on(points: list[tuple[date, Decimal]], day: date) -> Decimal | None:
    """The book's last point on or before ``day`` (points are date-ordered)."""
    value: Decimal | None = None
    for d, v in points:
        if d > day:
            break
        value = v
    return value


def _dedupe(notes: list[FxNote]) -> list[FxNote]:
    seen: set[tuple[str, date, date | None]] = set()
    out: list[FxNote] = []
    for n in notes:
        key = (n.currency, n.day, n.rate_date)
        if key not in seen:
            seen.add(key)
            out.append(n)
    return out


def growth_index(
    points: Sequence[tuple[date, Decimal]], flows: Sequence[tuple[date, Decimal]]
) -> list[tuple[date, Decimal]]:
    """A flow-free value series: starts at the first value, moves by each sub-period's TWR.

    Drawdown, Sharpe and the total return read it, so a new book or an
    imported buy never looks like a gain.
    """
    if not points:
        return []
    by_day: dict[date, Decimal] = defaultdict(Decimal)
    for day, amount in flows:
        by_day[day] += amount
    out = [points[0]]
    for (_, prev), (day, curr) in pairwise(points):
        last = out[-1][1]
        if prev <= 0:
            out.append((day, last))
            continue
        out.append((day, last * (curr - by_day.get(day, Decimal(0))) / prev))
    return out


# ---------------------------------------------------------------------------
# Reading the books
# ---------------------------------------------------------------------------


def book_series(
    session: Session, book: Portfolio, *, live: Decimal | None, as_of: date
) -> BookSeries:
    """One book's points (opening, snapshots, then ``live`` at ``as_of``) and flows."""
    assert book.id is not None
    opened = book.created_at.date()
    by_day: dict[date, Decimal] = {}
    if book.opening_nav is not None:
        by_day[opened] = book.opening_nav
    for snap in session.exec(
        select(PortfolioSnapshot)
        .where(PortfolioSnapshot.portfolio_id == book.id)
        .order_by(col(PortfolioSnapshot.date))
    ).all():
        if snap.date >= opened:
            by_day[snap.date] = snap.nav
    if live is not None:
        by_day[as_of] = live
    flows: list[tuple[date, Decimal]] = []
    if book.kind == BookKind.IMPORTED:
        flows = imported_flows(session, book)
    return BookSeries(
        book_id=book.id,
        currency=book.base_currency or "USD",
        opened=opened,
        points=sorted(by_day.items()),
        flows=flows,
        opening=book.opening_nav or Decimal(0),
    )


def imported_flows(session: Session, book: Portfolio) -> list[tuple[date, Decimal]]:
    """An imported book's buys (+cost and fees) and sells (-proceeds less fees), in base.

    The book is holdings-only (no cash), so the money behind each fill comes
    from, or goes to, outside it.
    """
    out: list[tuple[date, Decimal]] = []
    for trade in session.exec(
        select(Trade).where(Trade.portfolio_id == book.id).order_by(col(Trade.ts))
    ).all():
        rate = trade.fx_rate if trade.fx_rate is not None else Decimal(1)
        gross = trade.price * trade.quantity
        fees = trade.fees or Decimal(0)
        if trade.side == TradeSide.BUY:
            out.append((trade.ts.date(), (gross + fees) * rate))
        else:
            out.append((trade.ts.date(), -(gross - fees) * rate))
    return out


@dataclass(frozen=True, slots=True)
class CombinedView:
    books: list[Portfolio]
    valuations: list[PortfolioValuation]
    valuation: PortfolioValuation
    series: CombinedSeries


def combined_view(
    session: Session,
    books: list[Portfolio],
    *,
    display: str,
    as_of: date,
    with_series: bool = True,
) -> CombinedView:
    """Value every book in ``display``, merge them, and (optionally) build the series."""
    valuations = [compute_portfolio(session, b, display_currency=display) for b in books]
    merged = merge_valuations(valuations, display=display)
    if not with_series:
        return CombinedView(books, valuations, merged, CombinedSeries(display, None, [], [], []))

    currencies = {display} | {b.base_currency or "USD" for b in books}
    rates = RateBook.load(session, currencies, until=as_of)

    # Today's point: each book's live value back in its base at today's rate,
    # so every point of a book is in one currency before conversion.
    series: list[BookSeries] = []
    for book, val in zip(books, valuations, strict=True):
        base = book.base_currency or "USD"
        live_base = rates.convert(
            Decimal(val.total_value), src=display, dst=base, day=as_of, notes=[]
        )
        series.append(book_series(session, book, live=live_base, as_of=as_of))

    def convert(amount: Decimal, ccy: str, day: date, notes: list[FxNote]) -> Decimal | None:
        return rates.convert(amount, src=ccy, dst=display, day=day, notes=notes)

    combined = combine(series, display=display, convert=convert)
    warnings = list(merged.warnings) + fx_warnings(combined.notes, display=display)
    merged = _replace_warnings(merged, warnings)
    return CombinedView(books, valuations, merged, combined)


def history_series(
    session: Session, books: list[Portfolio], *, display: str, as_of: date
) -> CombinedSeries:
    """Snapshots only (no live point), summed: what ``/portfolio/history?book=all`` returns."""
    currencies = {display} | {b.base_currency or "USD" for b in books}
    rates = RateBook.load(session, currencies, until=as_of)
    series = [book_series(session, b, live=None, as_of=as_of) for b in books]

    def convert(amount: Decimal, ccy: str, day: date, notes: list[FxNote]) -> Decimal | None:
        return rates.convert(amount, src=ccy, dst=display, day=day, notes=notes)

    return combine(series, display=display, convert=convert)


def fx_warnings(notes: Sequence[FxNote], *, display: str) -> list[ValuationWarning]:
    """One warning per currency: the oldest stale rate used, or the dates with none."""
    stale: dict[str, FxNote] = {}
    missing: dict[str, list[date]] = defaultdict(list)
    for n in notes:
        if n.rate_date is None:
            missing[n.currency].append(n.day)
        elif n.currency not in stale or n.rate_date < (stale[n.currency].rate_date or n.day):
            stale[n.currency] = n
    out: list[ValuationWarning] = []
    for ccy, n in sorted(stale.items()):
        out.append(
            ValuationWarning(
                code="stale_fx_rate",
                subject=ccy,
                message=(
                    f"All books: the {ccy} rate used for {n.day.isoformat()} is from "
                    f"{n.rate_date.isoformat() if n.rate_date else 'an earlier day'}, older "
                    f"than the session before it, so the {display} total may be off."
                ),
            )
        )
    for ccy, days in sorted(missing.items()):
        out.append(
            ValuationWarning(
                code="no_fx_rate",
                subject=ccy,
                message=(
                    f"All books: no {ccy} rate is stored on or before "
                    f"{min(days).isoformat()}, so {len(days)} date(s) are left out of the "
                    f"combined {display} history."
                ),
            )
        )
    return out


def _replace_warnings(
    valuation: PortfolioValuation, warnings: list[ValuationWarning]
) -> PortfolioValuation:
    from dataclasses import replace

    return replace(valuation, warnings=warnings)


def merge_valuations(vals: Sequence[PortfolioValuation], *, display: str) -> PortfolioValuation:
    """One valuation over every book, all figures already in ``display``.

    The same ticker in two books becomes one holding: quantities and values
    are summed and the average cost is weighted by quantity. Warnings are
    kept once each.
    """

    def total(name: str) -> Decimal:
        return sum((Decimal(getattr(v, name)) for v in vals), Decimal(0))

    by_ticker: dict[str, list[PortfolioPosition]] = defaultdict(list)
    for v in vals:
        for p in v.positions:
            by_ticker[p.ticker].append(p)
    positions: list[PortfolioPosition] = []
    for ticker, parts in by_ticker.items():
        qty = sum((p.quantity for p in parts), Decimal(0))
        cost = sum((p.avg_cost * p.quantity for p in parts), Decimal(0))
        first = parts[0]
        positions.append(
            PortfolioPosition(
                ticker=ticker,
                name=first.name,
                quantity=qty,
                currency=first.currency,
                avg_cost=(cost / qty) if qty else Decimal(0),
                last_close=first.last_close,
                market_value_native=sum((p.market_value_native for p in parts), Decimal(0)),
                unrealized_pl_native=sum((p.unrealized_pl_native for p in parts), Decimal(0)),
                market_value=sum((p.market_value for p in parts), Decimal(0)),
                unrealized_pl=sum((p.unrealized_pl for p in parts), Decimal(0)),
                reserved_quantity=sum((p.reserved_quantity for p in parts), Decimal(0)),
                available_quantity=sum((p.available_quantity for p in parts), Decimal(0)),
            )
        )
    positions.sort(key=lambda p: p.market_value, reverse=True)

    cash: dict[str, list[Decimal]] = {}
    for v in vals:
        for c in v.cash_by_currency:
            amount, value = cash.get(c.currency, [Decimal(0), Decimal(0)])
            cash[c.currency] = [amount + c.amount, value + c.value]
    ordered = [display, *sorted(set(cash) - {display})]
    cash_by_currency = [
        CurrencyCash(ccy, cash[ccy][0], cash[ccy][1]) for ccy in ordered if ccy in cash
    ]

    warnings: list[ValuationWarning] = []
    seen: set[tuple[str, str]] = set()
    for v in vals:
        for w in v.warnings:
            if (w.code, w.subject) not in seen:
                seen.add((w.code, w.subject))
                warnings.append(w)

    return PortfolioValuation(
        portfolio_id=0,
        display_currency=display,
        base_currency=display,
        cash_balance=total("cash_balance"),
        reserved_cash=total("reserved_cash"),
        available_cash=total("available_cash"),
        positions=positions,
        option_positions=[o for v in vals for o in v.option_positions],
        market_value=total("market_value"),
        options_market_value=total("options_market_value"),
        total_value=total("total_value"),
        total_cost_basis=total("total_cost_basis"),
        unrealized_pl=total("unrealized_pl"),
        unrealized_pl_equity=total("unrealized_pl_equity"),
        unrealized_pl_options=total("unrealized_pl_options"),
        realized_pl=total("realized_pl"),
        realized_pl_unavailable=sum(v.realized_pl_unavailable for v in vals),
        fees_paid=total("fees_paid"),
        realized_pl_net=total("realized_pl_net"),
        warnings=warnings,
        cash_by_currency=cash_by_currency,
    )


def combined_xirr_flows(
    combined: CombinedSeries, *, live: Decimal, as_of: date
) -> list[tuple[date, Decimal]]:
    """Money out negative: the first value, every flow in, then today's value back."""
    if not combined.points:
        return []
    start_day, start_value = combined.points[0]
    flows = [(start_day, -start_value)]
    flows += [(day, -amount) for day, amount in combined.flows]
    flows.append((as_of, live))
    return flows
