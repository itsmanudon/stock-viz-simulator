"""Lots, realised gains and the FY computation (A7.12), pure.

- **Intraday first:** on each venue day, the day's bought and sold quantity
  that offset is intraday (speculative business income, not capital gains):
  P&L = (average sell - average buy) x the offset quantity. It is listed
  apart and not taxed here.
- **Delivery by FIFO** (CBDT Circular 768): each remaining sell takes the
  oldest open lots first. A sell with too few open shares is ``unmatched``
  (an opening lot is missing) and left out of the figures.
- **Term:** long term when held more than 12 months (``rules.is_long_term``).
- **Grandfathering** for long-term lots bought before 1 Feb 2018: cost is the
  higher of the actual cost and the lower of the FMV on 31 Jan 2018 and the
  sale value.
- **Set-off, then the exemption:** short-term losses against short-term gains,
  then long-term gains; long-term losses against long-term gains only; the
  Rs 1.25 lakh exemption on what long-term gain is left; the rest is carried
  forward (up to 8 years), not modelled across years here.
- Prices only: transfer expenses are not deducted (STT is not deductible;
  brokerage and other charges may be, which would lower the gain).
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from stockviz.services.tax.rules import (
    GRANDFATHER_CUTOFF,
    FyRules,
    is_long_term,
)

ZERO = Decimal(0)
RUPEE = Decimal("0.01")


@dataclass(frozen=True)
class Fill:
    ticker: str
    day: date
    side: str  # buy | sell
    quantity: Decimal
    price: Decimal
    seq: int = 0


@dataclass
class Lot:
    ticker: str
    bought: date
    quantity: Decimal
    price: Decimal


@dataclass(frozen=True)
class Realised:
    ticker: str
    bought: date
    sold: date
    quantity: Decimal
    cost: Decimal
    proceeds: Decimal
    gain: Decimal
    term: str  # short | long
    grandfathered: bool = False


@dataclass(frozen=True)
class Intraday:
    ticker: str
    day: date
    quantity: Decimal
    pnl: Decimal


@dataclass
class LotBook:
    open_lots: list[Lot] = field(default_factory=list)
    realised: list[Realised] = field(default_factory=list)
    intraday: list[Intraday] = field(default_factory=list)
    unmatched: list[tuple[str, date, Decimal]] = field(default_factory=list)


def _q(x: Decimal) -> Decimal:
    return x.quantize(RUPEE, rounding=ROUND_HALF_UP)


def _avg(fills: list[Fill]) -> Decimal:
    qty = sum((f.quantity for f in fills), ZERO)
    return sum((f.quantity * f.price for f in fills), ZERO) / qty if qty else ZERO


def build_lots(fills: list[Fill], fmv_2018: dict[str, Decimal] | None = None) -> LotBook:
    """Replay every fill (all years) into open lots, realised lots and intraday."""
    fmv_2018 = fmv_2018 or {}
    book = LotBook()
    by_key: dict[tuple[str, date], list[Fill]] = defaultdict(list)
    for f in fills:
        by_key[(f.ticker, f.day)].append(f)
    queues: dict[str, deque[Lot]] = defaultdict(deque)
    for ticker, day in sorted(by_key, key=lambda k: (k[1], k[0])):
        day_fills = sorted(by_key[(ticker, day)], key=lambda f: f.seq)
        buys = [f for f in day_fills if f.side == "buy"]
        sells = [f for f in day_fills if f.side == "sell"]
        bought = sum((f.quantity for f in buys), ZERO)
        sold = sum((f.quantity for f in sells), ZERO)
        offset = min(bought, sold)
        if offset > 0:
            book.intraday.append(
                Intraday(ticker, day, offset, _q((_avg(sells) - _avg(buys)) * offset))
            )
        buy_left = bought - offset
        sell_left = sold - offset
        if buy_left > 0:
            queues[ticker].append(Lot(ticker, day, buy_left, _avg(buys)))
        if sell_left > 0:
            price = _avg(sells)
            queue = queues[ticker]
            while sell_left > 0 and queue:
                lot = queue[0]
                take = min(lot.quantity, sell_left)
                cost = take * lot.price
                proceeds = take * price
                long = is_long_term(lot.bought, day)
                grandfathered = False
                fmv = fmv_2018.get(ticker)
                if long and lot.bought < GRANDFATHER_CUTOFF and fmv is not None:
                    deemed = max(cost, min(take * fmv, proceeds))
                    grandfathered = deemed != cost
                    cost = deemed
                book.realised.append(
                    Realised(
                        ticker,
                        lot.bought,
                        day,
                        take,
                        _q(cost),
                        _q(proceeds),
                        _q(proceeds - cost),
                        "long" if long else "short",
                        grandfathered,
                    )
                )
                lot.quantity -= take
                sell_left -= take
                if lot.quantity == 0:
                    queue.popleft()
            if sell_left > 0:
                book.unmatched.append((ticker, day, sell_left))
    book.open_lots = [lot for q in queues.values() for lot in q]
    return book


@dataclass(frozen=True)
class FyComputation:
    stcg: Decimal
    stcl: Decimal
    ltcg: Decimal
    ltcl: Decimal
    net_short: Decimal
    net_long_before_exemption: Decimal
    exemption_used: Decimal
    exemption_left: Decimal
    taxable_short: Decimal
    taxable_long: Decimal
    tax_short: Decimal
    tax_long: Decimal
    surcharge: Decimal
    cess: Decimal
    total_tax: Decimal
    loss_carried_short: Decimal
    loss_carried_long: Decimal
    intraday_pnl: Decimal


def compute_fy(
    realised: list[Realised],
    intraday: list[Intraday],
    rules: FyRules,
    *,
    surcharge_rate: Decimal = ZERO,
) -> FyComputation:
    in_fy = [r for r in realised if rules.start <= r.sold <= rules.end]
    stcg = sum((r.gain for r in in_fy if r.term == "short" and r.gain > 0), ZERO)
    stcl = -sum((r.gain for r in in_fy if r.term == "short" and r.gain < 0), ZERO)
    ltcg = sum((r.gain for r in in_fy if r.term == "long" and r.gain > 0), ZERO)
    ltcl = -sum((r.gain for r in in_fy if r.term == "long" and r.gain < 0), ZERO)
    # Long-term losses only against long-term gains.
    long_net = ltcg - ltcl
    loss_long = -long_net if long_net < 0 else ZERO
    long_net = max(long_net, ZERO)
    # Short-term losses against short-term gains, then long-term gains.
    short_net = stcg - stcl
    if short_net < 0:
        absorb = min(-short_net, long_net)
        long_net -= absorb
        loss_short = -short_net - absorb
        short_net = ZERO
    else:
        loss_short = ZERO
    exemption_used = min(long_net, rules.ltcg_exemption)
    taxable_long = long_net - exemption_used
    tax_short = _q(short_net * rules.stcg_rate)
    tax_long = _q(taxable_long * rules.ltcg_rate)
    rate = min(surcharge_rate, rules.surcharge_cap)
    surcharge = _q((tax_short + tax_long) * rate)
    cess = _q((tax_short + tax_long + surcharge) * rules.cess_rate)
    day_pnl = sum((i.pnl for i in intraday if rules.start <= i.day <= rules.end), ZERO)
    return FyComputation(
        stcg=stcg,
        stcl=stcl,
        ltcg=ltcg,
        ltcl=ltcl,
        net_short=short_net,
        net_long_before_exemption=long_net,
        exemption_used=exemption_used,
        exemption_left=rules.ltcg_exemption - exemption_used,
        taxable_short=short_net,
        taxable_long=taxable_long,
        tax_short=tax_short,
        tax_long=tax_long,
        surcharge=surcharge,
        cess=cess,
        total_tax=tax_short + tax_long + surcharge + cess,
        loss_carried_short=loss_short,
        loss_carried_long=loss_long,
        intraday_pnl=day_pnl,
    )
