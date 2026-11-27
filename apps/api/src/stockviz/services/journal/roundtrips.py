"""Round trips and their figures (A5.5, M10.3). Pure: no session, no clock.

**Grouping** is the replay episode rule (``services/replay/forensics.py::
reconstruct_episodes``), over any fill: in time order, a buy while flat opens
an entry, buys and sells add and reduce it, and the entry closes when the
quantity returns to zero. Partial sells stay in the entry; a buy after the
close opens a new one. A sell while flat belongs to no entry (paper and
replay books are long only, and an imported sell without shares never posts)
unless ``allow_short``: an imported book posts a sell while flat only as an
intraday short (the import engine's rule: covered by buys the same venue day),
so for imported books a sell while flat opens a **short** entry that buys
close. An entry still held at the end is open.

A short entry mirrors a long one: sells open and add, buys reduce; the entry
price is the sells' average and the exit the buys'; realized is each buy's
(average short price - price) x quantity; MAE is the highest high above the
average short price (adverse = price going up) and MFE the lowest low.

**Figures** (all in the instrument's currency):

- *average entry*: buy notional / shares bought (the drill's "average buy");
  *average exit*: sell notional / shares sold;
- *cost* for excursions: the ledger's average cost (re-averaged on buys,
  unchanged by sells, 6 places, as ``apply_fill`` and ``SimLedger``);
- *realized*: each sell's (price - average cost) x quantity, 6 places;
  *net P&L*: realized - every fee of the entry (+ for an open entry, the
  shares still held x (last close - average cost));
- *R*: net P&L / (|average entry - plan stop| x most shares held), the
  drill's definition (``services/drills/score.py``), equal to the
  backtester's for a single entry; null with a reason without a plan or stop;
- *MAE / MFE*: the worst and best (daily low or high - cost) while shares
  were held, per share, as a percent of cost, in money (x shares held that
  day) and in R (money / initial risk). Two bases:

  - ``exact_close`` (replay): fills are at the bar's close, so a bar's range
    counts only for shares held before its fills and the shares held after
    them see only its close (forensics' rule, the same numbers);
  - ``approximate_daily`` (paper and imported): only daily bars exist and a
    fill's place inside its day is unknown, so the entry day and the exit day
    count their whole range ("daily bars: may include moves before entry or
    after exit", design note question 6).

  A venue session with no stored bar inside the entry makes both null with
  the reason; intraday excursions are never shown as known.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

ZERO = Decimal(0)
HUNDRED = Decimal(100)
MICROS = Decimal("0.000001")
PCT = Decimal("0.0001")

Basis = Literal["exact_close", "approximate_daily", "exact_minutes"]

APPROXIMATE_NOTE = "Daily bars: may include moves before entry or after exit."
EXACT_NOTE = "Replay fills at the bar's close: the entry bar counts from its close."
MINUTES_NOTE = (
    "Minute bars: exact to the minute. Shares held at a minute's open count its whole "
    "range; a fill counts from its own price."
)


@dataclass(frozen=True)
class LedgerFill:
    """One fill of a book or replay session, in the instrument's currency."""

    key: str
    """Stable name of the fill (the entry key of an entry it opens)."""
    side: str  # "buy" | "sell"
    quantity: Decimal
    price: Decimal
    fees: Decimal
    at: datetime
    """Naive UTC (paper, imported) or the replay bar's label."""
    venue_date: date
    trade_id: int | None = None
    replay_fill_id: int | None = None
    plan_id: int | None = None
    time_known: bool = True
    fees_estimated: bool = False


Side = Literal["long", "short"]


@dataclass
class RoundTrip:
    fills: list[LedgerFill] = field(default_factory=list)
    closed: bool = False
    side: Side = "long"

    @property
    def opening_side(self) -> str:
        """The fill side that opens and adds: ``buy`` long, ``sell`` short."""
        return "sell" if self.side == "short" else "buy"

    @property
    def key(self) -> str:
        return self.fills[0].key

    @property
    def opened_at(self) -> datetime:
        return self.fills[0].at

    @property
    def closed_at(self) -> datetime | None:
        return self.fills[-1].at if self.closed else None

    @property
    def closing_fill(self) -> LedgerFill | None:
        return self.fills[-1] if self.closed else None


def group_round_trips(fills: Iterable[LedgerFill], *, allow_short: bool = False) -> list[RoundTrip]:
    """Flat to flat; ``fills`` already in time order (then id). ``allow_short``
    (imported books): a sell while flat opens a short entry."""
    trips: list[RoundTrip] = []
    current: RoundTrip | None = None
    qty = ZERO
    for fill in fills:
        if current is None:
            if fill.side == "buy":
                current = RoundTrip()
            elif allow_short:
                current = RoundTrip(side="short")
            else:
                continue
            qty = ZERO
        current.fills.append(fill)
        qty += fill.quantity if fill.side == current.opening_side else -fill.quantity
        if qty <= 0:
            current.closed = True
            trips.append(current)
            current = None
    if current is not None:
        trips.append(current)
    return trips


def reaverage(avg: Decimal, held: Decimal, quantity: Decimal, price: Decimal) -> Decimal:
    """The ledger's rule: ``(avg x held + price x qty) / (held + qty)``, 6 places."""
    cost = (price * quantity).quantize(MICROS)
    return ((avg * held + cost) / (held + quantity)).quantize(MICROS)


@dataclass(frozen=True)
class TradeFigures:
    avg_entry: Decimal
    avg_exit: Decimal | None
    avg_cost: Decimal
    bought: Decimal
    sold: Decimal
    peak_quantity: Decimal
    held: Decimal
    buy_notional: Decimal
    """The opening side's notional: buys for a long entry, sells for a short."""
    realized: Decimal
    fees: Decimal
    unrealized: Decimal | None
    net_pnl: Decimal
    return_pct: Decimal | None
    fees_estimated: bool


def trade_figures(trip: RoundTrip, *, mark_close: Decimal | None = None) -> TradeFigures:
    """Long: buys open. Short: sells open, so the entry is the sells' average,
    realized is (average short price - buy price) x quantity and ``buy_notional``
    (the return's base) is the sells' notional."""
    opening = trip.opening_side
    sign = Decimal(-1) if trip.side == "short" else Decimal(1)
    avg = held = peak = opened = closed_qty = ZERO
    open_notional = close_notional = realized = fees = ZERO
    for fill in trip.fills:
        fees += fill.fees
        if fill.side == opening:
            avg = reaverage(avg, held, fill.quantity, fill.price)
            held += fill.quantity
            opened += fill.quantity
            open_notional += (fill.quantity * fill.price).quantize(MICROS)
            peak = max(peak, held)
        else:
            # A buy covering a short and going long in one trade: the short
            # entry takes the covering part (the rest is a long holding).
            q = min(fill.quantity, held) if trip.side == "short" else fill.quantity
            realized += (sign * (fill.price - avg) * q).quantize(MICROS)
            held -= q
            closed_qty += q
            close_notional += (q * fill.price).quantize(MICROS)
    held = max(held, ZERO)
    unrealized: Decimal | None = None
    if not trip.closed and mark_close is not None and held > 0:
        unrealized = (sign * (mark_close - avg) * held).quantize(MICROS)
    net = realized - fees + (unrealized or ZERO)
    return TradeFigures(
        avg_entry=(open_notional / opened).quantize(MICROS) if opened else ZERO,
        avg_exit=(close_notional / closed_qty).quantize(MICROS) if closed_qty else None,
        avg_cost=avg,
        bought=opened if trip.side == "long" else closed_qty,
        sold=closed_qty if trip.side == "long" else opened,
        peak_quantity=peak,
        held=held,
        buy_notional=open_notional,
        realized=realized,
        fees=fees.quantize(MICROS),
        unrealized=unrealized,
        net_pnl=net.quantize(MICROS),
        return_pct=(net / open_notional * HUNDRED).quantize(PCT) if open_notional else None,
        fees_estimated=any(f.fees_estimated for f in trip.fills),
    )


@dataclass(frozen=True)
class RResult:
    value: float | None
    initial_risk: Decimal | None
    reason: str | None


SHORT_NO_PLAN = (
    "A short entry: plans for imported books are long only, so no plan or stop "
    "pairs with it and there is no initial risk."
)


def r_multiple(
    figures: TradeFigures,
    *,
    stop: Decimal | None,
    has_plan: bool,
    open_without_mark: bool = False,
    side: Side = "long",
) -> RResult:
    """Net P&L / (|average entry - stop| x most shares held)."""
    if not has_plan:
        if side == "short":
            return RResult(None, None, SHORT_NO_PLAN)
        return RResult(None, None, "No plan is paired with this entry.")
    if stop is None:
        return RResult(None, None, "The plan has no stop, so there is no initial risk.")
    risk = (abs(figures.avg_entry - stop) * figures.peak_quantity).quantize(MICROS)
    if risk <= 0:
        return RResult(None, None, "The stop equals the average entry: no initial risk.")
    if open_without_mark:
        return RResult(None, risk, "Open, and no close to mark it at.")
    return RResult(round(float(figures.net_pnl / risk), 4), risk, None)


@dataclass(frozen=True)
class Bar:
    day: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal


@dataclass(frozen=True)
class Excursion:
    per_share: Decimal
    pct: Decimal
    amount: Decimal
    shares: Decimal
    day: date
    price: Decimal
    r: float | None


@dataclass(frozen=True)
class Excursions:
    basis: Basis
    note: str
    mae: Excursion | None
    mfe: Excursion | None
    reason: str | None = None
    missing_sessions: tuple[date, ...] = ()
    sessions: int = 0


def excursions(
    trip: RoundTrip,
    bars: Sequence[Bar],
    *,
    basis: Basis,
    end_day: date,
    expected_sessions: Sequence[date] | None = None,
    initial_risk: Decimal | None = None,
) -> Excursions:
    """MAE and MFE over the bars from the entry's first day to ``end_day``."""
    note = EXACT_NOTE if basis == "exact_close" else APPROXIMATE_NOTE
    start = trip.fills[0].venue_date
    window = sorted((b for b in bars if start <= b.day <= end_day), key=lambda b: b.day)
    if expected_sessions is not None:
        have = {b.day for b in window}
        missing = tuple(d for d in expected_sessions if start <= d <= end_day and d not in have)
        if missing:
            return Excursions(
                basis, note, None, None,
                reason=f"No stored bar for {len(missing)} session(s) of this entry, first "
                f"{missing[0].isoformat()}: MAE and MFE are unknown.",
                missing_sessions=missing[:10], sessions=len(window),
            )  # fmt: skip
    if not window:
        return Excursions(basis, note, None, None, reason="No stored bars for this entry.")

    by_day: dict[date, list[LedgerFill]] = {}
    for fill in trip.fills:
        by_day.setdefault(fill.venue_date, []).append(fill)

    worst: Excursion | None = None
    best: Excursion | None = None
    short = trip.side == "short"
    opening = trip.opening_side

    def _mark(day: date, low: Decimal, high: Decimal, cost: Decimal, shares: Decimal) -> None:
        nonlocal worst, best
        if cost <= 0 or shares <= 0:
            return
        if short:  # adverse = the price going up
            adverse, adverse_at = cost - high, high
            favourable, favourable_at = cost - low, low
        else:
            adverse, adverse_at = low - cost, low
            favourable, favourable_at = high - cost, high
        if worst is None or adverse < worst.per_share:
            worst = _excursion(day, adverse_at, adverse, cost, shares, initial_risk)
        if best is None or favourable > best.per_share:
            best = _excursion(day, favourable_at, favourable, cost, shares, initial_risk)

    qty = avg = ZERO
    for bar in window:
        todays = by_day.get(bar.day, [])
        if basis == "exact_close":
            if qty > 0:
                _mark(bar.day, bar.low, bar.high, avg, qty)
            for fill in todays:
                if fill.side == opening:
                    avg = reaverage(avg, qty, fill.quantity, fill.price)
                    qty += fill.quantity
                else:
                    qty -= fill.quantity
            if todays and qty > 0:
                _mark(bar.day, bar.close, bar.close, avg, qty)
        else:
            most = qty
            for fill in todays:
                if fill.side == opening:
                    avg = reaverage(avg, qty, fill.quantity, fill.price)
                    qty += fill.quantity
                else:
                    qty -= fill.quantity
                most = max(most, qty)
            if most > 0:
                _mark(bar.day, bar.low, bar.high, avg, most)
    if worst is None or best is None:
        return Excursions(basis, note, None, None, reason="No bar while shares were held.")
    return Excursions(basis, note, worst, best, sessions=len(window))


@dataclass(frozen=True)
class MinuteBar:
    """One stored 1-minute bar: ``at`` its open (naive UTC), ``day`` the venue date."""

    at: datetime
    day: date
    high: Decimal
    low: Decimal


def minute_excursions(
    trip: RoundTrip,
    minutes: Sequence[MinuteBar],
    *,
    initial_risk: Decimal | None = None,
) -> Excursions:
    """A6.10: MAE and MFE from stored minutes, for a closed entry whose fills
    all carry a time. Shares held at a minute's open saw its whole range; a
    fill inside a minute counts from its own price (the rest of that minute
    is not known to be before or after it). Minutes run from the first fill's
    minute to the last fill's."""
    fills = sorted(trip.fills, key=lambda f: f.at)
    first = fills[0].at.replace(second=0, microsecond=0)
    last = fills[-1].at
    window = sorted((m for m in minutes if first <= m.at <= last), key=lambda m: m.at)
    if not window:
        return Excursions("exact_minutes", MINUTES_NOTE, None, None,
                          reason="No stored minutes for this entry.")  # fmt: skip
    worst: Excursion | None = None
    best: Excursion | None = None
    short = trip.side == "short"
    opening = trip.opening_side

    def _mark(day: date, low: Decimal, high: Decimal, cost: Decimal, shares: Decimal) -> None:
        nonlocal worst, best
        if cost <= 0 or shares <= 0:
            return
        if short:
            adverse, adverse_at = cost - high, high
            favourable, favourable_at = cost - low, low
        else:
            adverse, adverse_at = low - cost, low
            favourable, favourable_at = high - cost, high
        if worst is None or adverse < worst.per_share:
            worst = _excursion(day, adverse_at, adverse, cost, shares, initial_risk)
        if best is None or favourable > best.per_share:
            best = _excursion(day, favourable_at, favourable, cost, shares, initial_risk)

    qty = avg = ZERO
    index = 0
    for minute in window:
        if qty > 0:
            _mark(minute.day, minute.low, minute.high, avg, qty)
        # Fills inside this minute (or in an earlier minute with no bar).
        while index < len(fills) and fills[index].at.replace(second=0, microsecond=0) <= minute.at:
            fill = fills[index]
            index += 1
            if fill.side == opening:
                avg = reaverage(avg, qty, fill.quantity, fill.price)
                qty += fill.quantity
            else:
                qty -= fill.quantity
            if qty > 0:
                _mark(minute.day, fill.price, fill.price, avg, qty)
    if worst is None or best is None:
        return Excursions("exact_minutes", MINUTES_NOTE, None, None,
                          reason="No minute while shares were held.")  # fmt: skip
    return Excursions("exact_minutes", MINUTES_NOTE, worst, best,
                      sessions=len({m.day for m in window}))  # fmt: skip


def _excursion(
    day: date, price: Decimal, per_share: Decimal, cost: Decimal, shares: Decimal,
    risk: Decimal | None,
) -> Excursion:  # fmt: skip
    amount = (per_share * shares).quantize(MICROS)
    return Excursion(
        per_share=per_share.quantize(MICROS),
        pct=(per_share / cost * HUNDRED).quantize(PCT),
        amount=amount,
        shares=shares,
        day=day,
        price=price,
        r=round(float(amount / risk), 4) if risk else None,
    )


__all__ = [
    "APPROXIMATE_NOTE",
    "EXACT_NOTE",
    "MINUTES_NOTE",
    "SHORT_NO_PLAN",
    "Bar",
    "Basis",
    "Excursion",
    "Excursions",
    "LedgerFill",
    "MinuteBar",
    "RResult",
    "RoundTrip",
    "Side",
    "TradeFigures",
    "excursions",
    "group_round_trips",
    "minute_excursions",
    "r_multiple",
    "reaverage",
    "trade_figures",
]
