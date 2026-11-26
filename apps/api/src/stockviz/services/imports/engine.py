"""The imported book's holdings-only ledger, as a pure function (A5.3).

``replay_fills`` takes every fill of a book (the broker's, and the user's
opening lots) and returns what each one posts and the positions that result.
Both the preview (nothing written) and every rebuild (commit, batch delete,
an opening lot, a split) run it, so what the preview shows is what commit
posts.

Rules (design note, "Import"; questions 2-4):

- **Holdings only.** No cash: a buy adds shares at its price, a sell removes
  them and realises ``(price - average cost) x quantity`` against the
  weighted average, as ``apply_fill`` does. Fees never touch the position.
- **Order.** By execution time; on one instant, opening lots first, then the
  file's order.
- **A sell with too few shares held** (bought before the file's window) does
  not post: it is ``needs_opening_lot`` until the user enters an opening lot
  (date, quantity, average price) that covers it.
- **Intraday shorts.** A trade sell on an NSE/BSE equity listing while nothing
  is held, whose quantity (plus any short already open that day) the same
  scrip's later buys on the same venue day cover, is an intraday short: it
  posts (``short = "open"``) instead of waiting for an opening lot. Later buys
  that day cover it first (``short = "cover"``), realising
  ``(average short price - buy price) x quantity``; any rest of a covering buy
  adds to a long holding. A short never stays open overnight: a sell the day's
  buys do not cover keeps the opening-lot rule. Its fees are already intraday
  (the day's offsetting quantity), with no DP.
- **Splits.** A fill on a venue date before a recorded split's ex-date is
  restated (quantity x ratio, price / ratio) so it matches the split-adjusted
  bars; the broker fill keeps its as-traded numbers.
- **Basis uncertain.** When the restated price falls outside its day's
  split-adjusted bar (low - 2% to high + 2%), a bonus, rights issue or split
  is probably missing from ``corporate_actions`` (NSE bonus parsing is M1.3):
  the fill is marked and still posts.
- **Fees are estimated** from the A4.2 dated schedules on the as-traded
  numbers: the venue's equity delivery schedule, except the part of a day's
  buys and sells of one scrip that offset each other, which is priced on the
  intraday schedule ("inferred": the tradebook has no product column). DP
  is charged once per scrip per venue day on a delivery sell. Brokerage is
  per fill, which can overstate intraday brokerage when one order filled in
  several trades.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from stockviz.models.broker_import import (
    FILL_OPENING,
    PRODUCT_DELIVERY,
    PRODUCT_INTRADAY,
    PRODUCT_MIXED,
    STATUS_NEEDS_OPENING_LOT,
    STATUS_POSTED,
)
from stockviz.services.simulation import OrderSide, get_fee_schedule
from stockviz.services.simulation.fees import FeeBreakdown

MICROS = Decimal("0.000001")
BASIS_TOLERANCE = Decimal("0.02")

DELIVERY = {"XNSE": "in_equity_delivery_nse", "XBOM": "in_equity_delivery_bse"}
INTRADAY = {"XNSE": "in_equity_intraday_nse", "XBOM": "in_equity_intraday_bse"}


@dataclass(frozen=True, slots=True)
class LedgerFill:
    key: int
    instrument_id: int
    ticker: str
    venue: str
    kind: str  # trade | opening
    side: str  # buy | sell
    quantity: Decimal
    price: Decimal
    executed_at: datetime  # naive UTC
    venue_date: date
    seq: int = 0


@dataclass(slots=True)
class FillOutcome:
    key: int
    status: str
    quantity: Decimal
    price: Decimal
    held_before: Decimal
    realized_pnl: Decimal | None = None
    avg_cost_at_fill: Decimal | None = None
    product: str | None = None
    intraday_quantity: Decimal = Decimal(0)
    fees: Decimal = Decimal(0)
    fee_schedule: str | None = None
    fee_lines: list[dict[str, Any]] = field(default_factory=list)
    basis_uncertain: bool = False
    short: str | None = None
    """``open`` (an intraday short sale), ``cover`` (a buy covering it) or None."""

    @property
    def posted(self) -> bool:
        return self.status == STATUS_POSTED


@dataclass(frozen=True, slots=True)
class Holding:
    instrument_id: int
    ticker: str
    quantity: Decimal
    avg_cost: Decimal


@dataclass(slots=True)
class LedgerResult:
    outcomes: dict[int, FillOutcome]
    holdings: list[Holding]


Splits = dict[int, list[tuple[date, Decimal]]]
"""Per instrument: (ex_date, ratio) of every split due on its venue."""
DayRanges = dict[tuple[int, date], tuple[Decimal, Decimal]]
"""(instrument, venue date) -> the stored daily bar's (low, high)."""


def split_factor(splits: Splits, instrument_id: int, on: date) -> Decimal:
    factor = Decimal(1)
    for ex_date, ratio in splits.get(instrument_id, ()):
        if on < ex_date:
            factor *= ratio
    return factor


def _order_key(f: LedgerFill) -> tuple[datetime, int, int]:
    return (f.executed_at, 0 if f.kind == FILL_OPENING else 1, f.seq)


def _intraday_allocation(fills: list[LedgerFill]) -> dict[int, Decimal]:
    """Per fill, the quantity that offsets the other side the same venue day."""
    days: dict[tuple[int, date], list[LedgerFill]] = defaultdict(list)
    for f in fills:
        if f.kind != FILL_OPENING:
            days[(f.instrument_id, f.venue_date)].append(f)
    out: dict[int, Decimal] = {}
    for day_fills in days.values():
        buys = sum((f.quantity for f in day_fills if f.side == "buy"), Decimal(0))
        sells = sum((f.quantity for f in day_fills if f.side == "sell"), Decimal(0))
        left = {"buy": min(buys, sells), "sell": min(buys, sells)}
        for f in sorted(day_fills, key=_order_key):
            take = min(f.quantity, left[f.side])
            left[f.side] -= take
            out[f.key] = take
    return out


def _later_buys(fills: list[LedgerFill]) -> dict[int, Decimal]:
    """Per trade fill (in order): the same scrip's buy quantity after it that venue day."""
    days: dict[tuple[int, date], list[LedgerFill]] = defaultdict(list)
    for f in fills:
        if f.kind != FILL_OPENING:
            days[(f.instrument_id, f.venue_date)].append(f)
    out: dict[int, Decimal] = {}
    for day_fills in days.values():
        after = Decimal(0)
        for f in reversed(day_fills):  # already in order
            out[f.key] = after
            if f.side == "buy":
                after += f.quantity
    return out


def _label(lines: list[dict[str, Any]], prefix: str) -> list[dict[str, Any]]:
    return [{**line, "label": f"{prefix} {line['label'].lower()}"} for line in lines]


def estimate_fees(
    f: LedgerFill, intraday_qty: Decimal, *, dp_due: bool
) -> tuple[Decimal, str | None, list[dict[str, Any]], str]:
    """Estimated fees (native, INR), the main schedule, the lines and the product."""
    from stockviz.services.trading.execute import fee_lines_json

    delivery_qty = f.quantity - intraday_qty
    side = OrderSide.BUY if f.side == "buy" else OrderSide.SELL
    parts: list[tuple[str, str, FeeBreakdown]] = []
    if intraday_qty > 0 and f.venue in INTRADAY:
        schedule = get_fee_schedule(INTRADAY[f.venue])
        parts.append(
            ("Intraday", schedule.name, schedule.fees(side, intraday_qty, f.price, on=f.venue_date))
        )
    if delivery_qty > 0 and f.venue in DELIVERY:
        schedule = get_fee_schedule(DELIVERY[f.venue])
        parts.append(
            (
                "Delivery",
                schedule.name,
                schedule.fees(side, delivery_qty, f.price, on=f.venue_date, dp_due=dp_due),
            )
        )
    if intraday_qty <= 0:
        product = PRODUCT_DELIVERY
    elif delivery_qty <= 0:
        product = PRODUCT_INTRADAY
    else:
        product = PRODUCT_MIXED
    total = sum((b.total for _p, _n, b in parts), Decimal(0)).quantize(MICROS)
    lines: list[dict[str, Any]] = []
    for prefix, _name, breakdown in parts:
        json_lines = fee_lines_json(breakdown)
        lines.extend(_label(json_lines, prefix) if len(parts) > 1 else json_lines)
    main = parts[0][1] if parts else None
    return total, main, lines, product


def replay_fills(
    fills: list[LedgerFill],
    *,
    splits: Splits | None = None,
    day_ranges: DayRanges | None = None,
) -> LedgerResult:
    splits = splits or {}
    day_ranges = day_ranges or {}
    ordered = sorted(fills, key=_order_key)
    intraday = _intraday_allocation(ordered)
    later_buys = _later_buys(ordered)
    dp_seen: set[tuple[int, date]] = set()
    held: dict[int, Decimal] = defaultdict(Decimal)
    avg: dict[int, Decimal] = defaultdict(Decimal)
    short: dict[int, Decimal] = defaultdict(Decimal)  # open intraday short, restated
    short_avg: dict[int, Decimal] = defaultdict(Decimal)
    tickers: dict[int, str] = {}
    outcomes: dict[int, FillOutcome] = {}

    for f in ordered:
        tickers[f.instrument_id] = f.ticker
        factor = split_factor(splits, f.instrument_id, f.venue_date)
        qty = (f.quantity * factor).quantize(MICROS)
        price = (f.price / factor).quantize(MICROS)
        before = held[f.instrument_id]
        out = FillOutcome(
            key=f.key, status=STATUS_POSTED, quantity=qty, price=price, held_before=before
        )
        if f.kind != FILL_OPENING:
            intra = intraday.get(f.key, Decimal(0))
            dp_due = False
            if f.side == "sell" and f.quantity - intra > 0:
                day = (f.instrument_id, f.venue_date)
                dp_due = day not in dp_seen
                dp_seen.add(day)
            out.fees, out.fee_schedule, out.fee_lines, out.product = estimate_fees(
                f, intra, dp_due=dp_due
            )
            out.intraday_quantity = intra
            bar = day_ranges.get((f.instrument_id, f.venue_date))
            if bar is not None:
                low, high = bar
                out.basis_uncertain = not (
                    low * (1 - BASIS_TOLERANCE) <= price <= high * (1 + BASIS_TOLERANCE)
                )
        iid = f.instrument_id
        if f.side == "buy":
            rest = qty
            if short[iid] > 0 and f.kind != FILL_OPENING:
                cover = min(qty, short[iid])
                out.short = "cover"
                out.avg_cost_at_fill = short_avg[iid]
                out.realized_pnl = ((short_avg[iid] - price) * cover).quantize(MICROS)
                short[iid] -= cover
                if short[iid] == 0:
                    short_avg[iid] = Decimal(0)
                rest = qty - cover
            if rest > 0:
                total = avg[iid] * before + price * rest
                held[iid] = before + rest
                avg[iid] = (total / held[iid]).quantize(MICROS)
        elif before >= qty:
            out.avg_cost_at_fill = avg[iid]
            out.realized_pnl = ((price - avg[iid]) * qty).quantize(MICROS)
            held[iid] = before - qty
            if held[iid] == 0:
                avg[iid] = Decimal(0)
        elif (
            before == 0
            and f.kind != FILL_OPENING
            and f.venue in INTRADAY
            and (later_buys.get(f.key, Decimal(0)) * factor).quantize(MICROS) >= short[iid] + qty
        ):
            out.short = "open"
            short_avg[iid] = (
                (short_avg[iid] * short[iid] + price * qty) / (short[iid] + qty)
            ).quantize(MICROS)
            short[iid] += qty
        else:
            out.status = STATUS_NEEDS_OPENING_LOT
        outcomes[f.key] = out

    holdings = [
        Holding(iid, tickers[iid], qty, avg[iid]) for iid, qty in sorted(held.items()) if qty > 0
    ]
    return LedgerResult(outcomes=outcomes, holdings=holdings)
