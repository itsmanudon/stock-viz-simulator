"""Round trips and their figures (A5.5, M10.3). Pure: no session, no clock.

**Grouping** is the replay episode rule (``services/replay/forensics.py::
reconstruct_episodes``), over any fill: in time order, a buy while flat opens
an entry, buys and sells add and reduce it, and the entry closes when the
quantity returns to zero. Partial sells stay in the entry; a buy after the
close opens a new one. A sell while flat belongs to no entry (paper, imported
and replay books are long only, and an imported sell without shares never
posts). An entry still held at the end is open.

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

Basis = Literal["exact_close", "approximate_daily"]

APPROXIMATE_NOTE = "Daily bars: may include moves before entry or after exit."
EXACT_NOTE = "Replay fills at the bar's close: the entry bar counts from its close."


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


@dataclass
class RoundTrip:
    fills: list[LedgerFill] = field(default_factory=list)
    closed: bool = False

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


def group_round_trips(fills: Iterable[LedgerFill]) -> list[RoundTrip]:
    """Flat to flat; ``fills`` already in time order (then id)."""
    trips: list[RoundTrip] = []
    current: RoundTrip | None = None
    qty = ZERO
    for fill in fills:
        if current is None:
            if fill.side != "buy":
                continue
            current = RoundTrip()
            qty = ZERO
        current.fills.append(fill)
        qty += fill.quantity if fill.side == "buy" else -fill.quantity
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
    realized: Decimal
    fees: Decimal
    unrealized: Decimal | None
    net_pnl: Decimal
    return_pct: Decimal | None
    fees_estimated: bool


def trade_figures(trip: RoundTrip, *, mark_close: Decimal | None = None) -> TradeFigures:
    avg = held = peak = bought = sold = ZERO
    buy_notional = sell_notional = realized = fees = ZERO
    for fill in trip.fills:
        fees += fill.fees
        if fill.side == "buy":
            avg = reaverage(avg, held, fill.quantity, fill.price)
            held += fill.quantity
            bought += fill.quantity
            buy_notional += (fill.quantity * fill.price).quantize(MICROS)
            peak = max(peak, held)
        else:
            realized += ((fill.price - avg) * fill.quantity).quantize(MICROS)
            held -= fill.quantity
            sold += fill.quantity
            sell_notional += (fill.quantity * fill.price).quantize(MICROS)
    held = max(held, ZERO)
    unrealized: Decimal | None = None
    if not trip.closed and mark_close is not None and held > 0:
        unrealized = ((mark_close - avg) * held).quantize(MICROS)
    net = realized - fees + (unrealized or ZERO)
    return TradeFigures(
        avg_entry=(buy_notional / bought).quantize(MICROS) if bought else ZERO,
        avg_exit=(sell_notional / sold).quantize(MICROS) if sold else None,
        avg_cost=avg,
        bought=bought,
        sold=sold,
        peak_quantity=peak,
        held=held,
        buy_notional=buy_notional,
        realized=realized,
        fees=fees.quantize(MICROS),
        unrealized=unrealized,
        net_pnl=net.quantize(MICROS),
        return_pct=(net / buy_notional * HUNDRED).quantize(PCT) if buy_notional else None,
        fees_estimated=any(f.fees_estimated for f in trip.fills),
    )


@dataclass(frozen=True)
class RResult:
    value: float | None
    initial_risk: Decimal | None
    reason: str | None


def r_multiple(
    figures: TradeFigures, *, stop: Decimal | None, has_plan: bool, open_without_mark: bool = False
) -> RResult:
    """Net P&L / (|average entry - stop| x most shares held)."""
    if not has_plan:
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

    def _mark(day: date, low: Decimal, high: Decimal, cost: Decimal, shares: Decimal) -> None:
        nonlocal worst, best
        if cost <= 0 or shares <= 0:
            return
        adverse, favourable = low - cost, high - cost
        if worst is None or adverse < worst.per_share:
            worst = _excursion(day, low, adverse, cost, shares, initial_risk)
        if best is None or favourable > best.per_share:
            best = _excursion(day, high, favourable, cost, shares, initial_risk)

    qty = avg = ZERO
    for bar in window:
        todays = by_day.get(bar.day, [])
        if basis == "exact_close":
            if qty > 0:
                _mark(bar.day, bar.low, bar.high, avg, qty)
            for fill in todays:
                if fill.side == "buy":
                    avg = reaverage(avg, qty, fill.quantity, fill.price)
                    qty += fill.quantity
                else:
                    qty -= fill.quantity
            if todays and qty > 0:
                _mark(bar.day, bar.close, bar.close, avg, qty)
        else:
            most = qty
            for fill in todays:
                if fill.side == "buy":
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
    "Bar",
    "Basis",
    "Excursion",
    "Excursions",
    "LedgerFill",
    "RResult",
    "RoundTrip",
    "TradeFigures",
    "excursions",
    "group_round_trips",
    "r_multiple",
    "reaverage",
    "trade_figures",
]
