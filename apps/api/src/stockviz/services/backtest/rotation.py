"""Cross-sectional rotation (A4.4, the rotation part of M7.1). Pure.

:func:`run_rotation` holds the top ``N`` symbols of a universe by a numeric
Rule DSL expression (higher ranks first) and rebalances on a schedule.
``rotation_run.py`` loads the data and the schedule's dates.

**Timing (no look-ahead).** A rebalance ranks on the *last session of each
week or month on the venue calendar* (:func:`rebalance_signals`), using each
symbol's value at that session's close: the vector-mode series, which the
conformance suite holds equal to point mode, so a value never reads a later
bar. Orders fill on each symbol's *next* bar under the run's fill profile
(``next_open``: its open; ``next_close``: its close), through
:func:`fills.book` (the kernel and ``SimLedger``). A first rebalance ranks
on the last session before the window, so the run is invested from its
first session. A period still running at the window's end does not
rebalance.

**Ranking.** Only symbols with a bar on the rebalance session and a known
value are ranked (an unknown is never ranked, and is listed with why). Ties
go to the ticker that sorts first. With ``buffer`` B, a holding is kept while
its rank is at most N + B (hysteresis); free slots take the best-ranked
symbols not held.

**Weights.** Each of the N slots is 1/N of the equity at the rebalance close
(``equal``), or the target names share k/N of it (k names held) by inverse
volatility (``inverse_volatility``: weight proportional to 1 / the standard deviation of
the last :data:`VOL_WINDOW` daily returns, known at the rebalance close; a
symbol whose volatility is unknown is not ranked). Fewer ranked names than N
leave the spare slots in cash. **Every rebalance resizes to the targets:**
names leaving are sold in full, names that stay are trimmed or topped up to
their weight (whole shares at the fill bar's expected price), and names
entering are bought to theirs, capped by free cash. Trims are ``resize``
round trips at the holding's average price; top-ups re-average it.

**Cash filter.** An optional rule judged at the rebalance close (by the
caller: on the market index). Met: everything is sold and the run holds cash
until a later rebalance where it is not met. Unknown: it does not act
(counted).

**Orders.** Within a day, sells fill before buys. A new rebalance replaces
orders still waiting for a bar (counted as ``replaced``). Whole shares;
fees come out of the same cash. With ``adv_cap_pct`` a buy takes at most that
share of the 20-day average traded value (the 20 bars before the fill bar);
exits are never capped but are flagged above it.

Positions still held at the end are marked at the last close (``open``),
not sold.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Literal

from stockviz.services.backtest.engine import (
    DEFAULT_RISK_FREE_RATE,
    _max_drawdown,
    _sharpe,
)
from stockviz.services.backtest.fills import BookedFill, book
from stockviz.services.markets.calendar import is_session
from stockviz.services.simulation import (
    LEGACY_CLOSE,
    NEXT_OPEN,
    CostModel,
    ExecutionProfile,
    FeeSchedule,
    MarketSnapshot,
    OrderIntent,
    OrderSide,
    SimInsufficientCash,
    SimLedger,
    SimulationOrderType,
    cost_adjusted,
)

MICROS = Decimal("0.000001")
ADV_BARS = 20
VOL_WINDOW = 63
"""Daily returns behind the inverse-volatility weight (about a quarter)."""

Schedule = Literal["weekly", "monthly"]
Weighting = Literal["equal", "inverse_volatility"]


class RotationError(ValueError):
    """The rotation cannot run on this data (a 400)."""


# --- the schedule -------------------------------------------------------------


def _period_key(day: date, schedule: Schedule) -> tuple[int, int]:
    if schedule == "weekly":
        iso = day.isocalendar()
        return (iso.year, iso.week)
    return (day.year, day.month)


def _period_end(day: date, schedule: Schedule) -> date:
    if schedule == "weekly":
        return day + timedelta(days=6 - day.weekday())
    nxt = date(day.year + (day.month == 12), day.month % 12 + 1, 1)
    return nxt - timedelta(days=1)


def last_session_of_period(day: date, schedule: Schedule, venue: str) -> date | None:
    """The venue's last session in ``day``'s week (ISO, Monday to Sunday) or
    month; None when the period has no session."""
    end = _period_end(day, schedule)
    key = _period_key(day, schedule)
    probe = end
    while _period_key(probe, schedule) == key:
        if is_session(probe, venue):
            return probe
        probe -= timedelta(days=1)
    return None


def rebalance_signals(start: date, end: date, schedule: Schedule, venue: str) -> list[date]:
    """The rebalance sessions for a window: the last session before
    ``start`` (the first ranking), then the last session of every week or
    month that ends inside [``start``, ``end``]. A period whose last session
    falls after ``end`` is still running and is left out."""
    out: list[date] = []
    probe = start - timedelta(days=1)
    for _ in range(14):
        if is_session(probe, venue):
            out.append(probe)
            break
        probe -= timedelta(days=1)
    day = start
    seen: set[tuple[int, int]] = set()
    while day <= end:
        key = _period_key(day, schedule)
        if key not in seen:
            seen.add(key)
            last = last_session_of_period(day, schedule, venue)
            if last is not None and start <= last <= end and (not out or last > out[-1]):
                out.append(last)
        day = _period_end(day, schedule) + timedelta(days=1)
    return out


# --- inputs and outputs ---------------------------------------------------------


@dataclass(frozen=True)
class RotationSymbol:
    ticker: str
    dates: list[date]
    ts: list[datetime]
    open: list[Decimal]
    high: list[Decimal]
    low: list[Decimal]
    close: list[Decimal]
    volume: list[Decimal]
    score: list[float | None]
    """The ranking expression's value at each bar's close (None: unknown)."""
    first: int = 0
    """Index of the first bar in the window; earlier bars are warm-up."""
    vol: list[float | None] | None = None
    """Standard deviation of the last ``VOL_WINDOW`` daily returns at each bar."""


@dataclass(frozen=True)
class RankEntry:
    ticker: str
    value: float
    rank: int


@dataclass(frozen=True)
class Unranked:
    ticker: str
    reason: Literal["no_bar", "unknown", "volatility_unknown"]


@dataclass
class Rebalance:
    signal_date: date
    equity: Decimal
    cash_filter: bool | None = None
    skipped: str | None = None
    """Why nothing changed: ``no_data`` (no symbol had a bar that session)."""
    ranked: list[RankEntry] = field(default_factory=list)
    unranked: list[Unranked] = field(default_factory=list)
    before: list[str] = field(default_factory=list)
    target: list[str] = field(default_factory=list)
    entered: list[str] = field(default_factory=list)
    exited: list[str] = field(default_factory=list)
    weights: dict[str, float] = field(default_factory=dict)
    """Target weight of every name held after (fractions of the equity)."""
    trade_dates: list[date] = field(default_factory=list)
    bought: Decimal = Decimal(0)
    sold: Decimal = Decimal(0)
    replaced: int = 0
    """Orders of the previous rebalance still waiting for a bar, replaced."""
    not_filled: dict[str, int] = field(default_factory=dict)
    """Buys not filled: ``no_cash``, ``adv_cap`` (no whole share allowed)."""

    @property
    def turnover(self) -> float:
        """One-way turnover: (bought + sold) / 2 / equity at the rebalance close."""
        if self.equity <= 0:
            return 0.0
        return float((self.bought + self.sold) / 2 / self.equity)


@dataclass(frozen=True)
class RotationTrade:
    ticker: str
    entry_date: date
    entry_price: Decimal
    entry_reference: Decimal
    exit_date: date
    exit_price: Decimal
    exit_reference: Decimal
    quantity: Decimal
    entry_fees: Decimal
    exit_fees: Decimal
    pnl: Decimal
    return_pct: float
    reason: Literal["rebalance", "resize", "cash_filter", "end_of_data"]
    open: bool
    bars_held: int
    requested_quantity: Decimal | None = None
    exit_adv_pct: float | None = None


@dataclass(frozen=True)
class RotationResult:
    trades: list[RotationTrade]
    rebalances: list[Rebalance]
    equity_curve: list[tuple[date, Decimal]]
    final_nav: Decimal
    total_return: float
    sharpe: float
    max_drawdown: float
    total_fees: Decimal
    price_costs: Decimal
    benchmark_return: float
    benchmark_final_nav: Decimal
    fee_versions: dict[date, int] = field(default_factory=dict)
    fills_before_coverage: int = 0
    partial_entries: int = 0
    adv_unknown: int = 0
    cash_filter_unknown: int = 0
    unfilled_at_end: int = 0

    @property
    def gross_final_nav(self) -> Decimal:
        return self.final_nav + self.total_fees + self.price_costs

    @property
    def total_costs(self) -> Decimal:
        return (self.total_fees + self.price_costs).quantize(MICROS)

    @property
    def skip_reasons(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in self.rebalances:
            for k, v in r.not_filled.items():
                out[k] = out.get(k, 0) + v
        return out


@dataclass
class _Holding:
    quantity: Decimal
    entry_date: date
    price: Decimal
    """Average fill price of the shares held."""
    reference: Decimal
    fees: Decimal
    """Entry fees of the shares held (a partial sale takes its share)."""
    requested: Decimal | None
    bars_held: int = 0


@dataclass
class _Order:
    kind: str  # "exit" (sell all) | "target" (resize to ``weight`` of the equity)
    signal_date: date
    rebalance: int
    weight: float = 0.0
    reason: str = "rebalance"


def _weights(
    target: list[str], top_n: int, weighting: Weighting, vols: dict[str, float]
) -> dict[str, float]:
    if not target:
        return {}
    if weighting == "equal":
        return dict.fromkeys(target, 1.0 / top_n)
    inverse = {t: 1.0 / vols[t] for t in target}
    total = sum(inverse.values())
    share = len(target) / top_n
    return {t: share * v / total for t, v in inverse.items()}


def run_rotation(
    symbols: list[RotationSymbol],
    *,
    signals: list[date],
    cash_filter: dict[date, bool | None] | None = None,
    top_n: int,
    buffer: int = 0,
    weighting: Weighting = "equal",
    initial_cash: Decimal,
    profile: ExecutionProfile = NEXT_OPEN,
    costs: CostModel | None = None,
    schedule: FeeSchedule,
    commission_bps: Decimal = Decimal(0),
    brokerage: str = "zerodha",
    adv_cap_pct: float | None = None,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
) -> RotationResult:
    if initial_cash <= 0:
        raise RotationError("initial_cash must be positive")
    if top_n < 1:
        raise RotationError("top_n must be at least 1")
    if profile not in (NEXT_OPEN, LEGACY_CLOSE):
        raise RotationError(f"unsupported profile {profile.name}")
    if weighting == "inverse_volatility" and any(s.vol is None for s in symbols):
        raise RotationError("inverse_volatility weighting needs each symbol's volatility")
    costs = costs or CostModel()
    at_open = profile == NEXT_OPEN
    by_ticker = {s.ticker: s for s in symbols}
    index_of = {s.ticker: {d: i for i, d in enumerate(s.dates)} for s in symbols}
    window_days = {d for s in symbols for d in s.dates[s.first :]}
    last_bar = max((s.dates[-1] for s in symbols if s.dates), default=None)
    signals = [d for d in signals if last_bar is not None and d <= last_bar]
    signal_set = set(signals)
    start_day = min([*signals[:1], *(s.dates[s.first] for s in symbols if s.first < len(s.dates))],
                    default=None)  # fmt: skip
    timeline = sorted(
        {d for s in symbols for d in s.dates if start_day is not None and d >= start_day}
        | signal_set
    )

    ledger = SimLedger(cash=initial_cash)
    holdings: dict[str, _Holding] = {}
    pending: dict[str, _Order] = {}
    last_close: dict[str, Decimal] = {}
    rebalances: list[Rebalance] = []
    trades: list[RotationTrade] = []
    dp_seen: set[tuple[str, date]] = set()
    fee_versions: dict[date, int] = {}
    counters = {"before": 0, "partial": 0, "adv_unknown": 0, "filter_unknown": 0}
    price_costs = Decimal(0)
    curve: list[tuple[date, Decimal]] = []

    def snapshot(s: RotationSymbol, i: int) -> MarketSnapshot:
        return MarketSnapshot(
            ticker=s.ticker, observed_at=s.ts[i], interval="1d", open=s.open[i],
            high=s.high[i], low=s.low[i], close=s.close[i], volume=s.volume[i],
        )  # fmt: skip

    def adv(s: RotationSymbol, i: int) -> Decimal | None:
        if i < ADV_BARS:
            return None
        return (
            sum((s.close[j] * s.volume[j] for j in range(i - ADV_BARS, i)), Decimal(0)) / ADV_BARS
        )

    def booked(s: RotationSymbol, i: int, order: OrderIntent) -> BookedFill | None:
        fill = book(ledger, order, snapshot(s, i), profile, costs=costs, schedule=schedule,
                    commission_bps=commission_bps, on=s.dates[i], brokerage=brokerage,
                    dp_seen=dp_seen)  # fmt: skip
        if fill is not None:
            version = fill.fees.version
            if version is not None:
                key = version.effective_from
                fee_versions[key] = fee_versions.get(key, 0) + 1
            if fill.fees.before_coverage:
                counters["before"] += 1
        return fill

    def note_trade(r: Rebalance, day: date) -> None:
        if day not in r.trade_dates:
            r.trade_dates.append(day)

    def submitted(s: RotationSymbol, i: int, order: _Order) -> datetime:
        j = index_of[s.ticker].get(order.signal_date)
        return s.ts[j] if j is not None else s.ts[i]

    def target_quantity(s: RotationSymbol, i: int, order: _Order) -> Decimal:
        """Whole shares worth ``weight`` of the equity at the rebalance close,
        at this bar's expected buy price."""
        reference = s.open[i] if at_open else s.close[i]
        expected = cost_adjusted(reference, OrderSide.BUY, costs)
        if expected <= 0:
            return Decimal(0)
        value = rebalances[order.rebalance].equity * Decimal(repr(order.weight))
        return (value / expected).to_integral_value(rounding=ROUND_FLOOR)

    def sell(s: RotationSymbol, i: int, order: _Order, quantity: Decimal, reason: str) -> None:
        nonlocal price_costs
        h = holdings[s.ticker]
        intent = OrderIntent(ticker=s.ticker, side=OrderSide.SELL,
                             order_type=SimulationOrderType.MARKET, quantity=quantity,
                             submitted_at=submitted(s, i, order))  # fmt: skip
        fill = booked(s, i, intent)
        assert fill is not None, "a market sell always fills"
        price_costs += abs(fill.price - fill.reference) * quantity
        over: float | None = None
        if adv_cap_pct is not None:
            avg = adv(s, i)
            share = (fill.price * quantity / avg * 100) if avg else None
            if share is not None and share > Decimal(repr(adv_cap_pct)):
                over = round(float(share), 4)
        r = rebalances[order.rebalance]
        r.sold += fill.price * quantity
        note_trade(r, s.dates[i])
        entry_fees = (h.fees * quantity / h.quantity).quantize(MICROS)
        trades.append(_trade(s.ticker, h, quantity, entry_fees, s.dates[i], fill.price,
                             fill.reference, fill.fees.total, reason, open_=False,
                             exit_adv_pct=over))  # fmt: skip
        h.fees -= entry_fees
        h.quantity -= quantity
        if h.quantity <= 0:
            del holdings[s.ticker]

    def buy(s: RotationSymbol, i: int, order: _Order, quantity: Decimal) -> None:
        nonlocal price_costs
        r = rebalances[order.rebalance]
        reference = s.open[i] if at_open else s.close[i]
        expected = cost_adjusted(reference, OrderSide.BUY, costs)
        cash = ledger.cash
        quantity = min(quantity, (cash / expected).to_integral_value(rounding=ROUND_FLOOR))
        requested: Decimal | None = None
        if adv_cap_pct is not None and quantity > 0:
            avg = adv(s, i)
            if avg is None:
                counters["adv_unknown"] += 1
            else:
                most = (avg * Decimal(repr(adv_cap_pct)) / 100 / expected).to_integral_value(
                    rounding=ROUND_FLOOR
                )
                if most < quantity:
                    if most <= 0:
                        r.not_filled["adv_cap"] = r.not_filled.get("adv_cap", 0) + 1
                        return
                    requested, quantity = quantity, most
        while quantity > 0:
            fee = schedule.fees(OrderSide.BUY, quantity, expected, commission_bps=commission_bps,
                                on=s.dates[i], brokerage=brokerage).total  # fmt: skip
            if expected * quantity + fee <= cash:
                break
            short_by = (expected * quantity + fee - cash) / expected
            quantity -= max(Decimal(1), short_by.to_integral_value(rounding=ROUND_CEILING))
        if quantity <= 0:
            r.not_filled["no_cash"] = r.not_filled.get("no_cash", 0) + 1
            return
        intent = OrderIntent(ticker=s.ticker, side=OrderSide.BUY,
                             order_type=SimulationOrderType.MARKET, quantity=quantity,
                             submitted_at=submitted(s, i, order))  # fmt: skip
        try:
            fill = booked(s, i, intent)
        except SimInsufficientCash:
            r.not_filled["no_cash"] = r.not_filled.get("no_cash", 0) + 1
            return
        assert fill is not None, "a market buy always fills"
        price_costs += abs(fill.price - fill.reference) * quantity
        if requested is not None:
            counters["partial"] += 1
        r.bought += fill.price * quantity
        note_trade(r, s.dates[i])
        h = holdings.get(s.ticker)
        if h is None:
            holdings[s.ticker] = _Holding(quantity, s.dates[i], fill.price, fill.reference,
                                          fill.fees.total, requested)  # fmt: skip
        else:
            total = h.quantity + quantity
            h.price = ((h.price * h.quantity + fill.price * quantity) / total).quantize(MICROS)
            h.reference = ((h.reference * h.quantity + fill.reference * quantity) / total).quantize(
                MICROS
            )
            h.fees += fill.fees.total
            h.quantity = total

    def decide(day: date) -> None:
        held = sorted(holdings)
        closes = dict(last_close)
        equity = ledger.equity(closes)
        r = Rebalance(signal_date=day, equity=equity.quantize(MICROS), before=held)
        r.replaced = len(pending)
        pending.clear()
        if not any(day in index_of[s.ticker] for s in symbols):
            r.skipped = "no_data"
            r.target = held
            rebalances.append(r)
            return
        known: list[tuple[str, float]] = []
        vols: dict[str, float] = {}
        for s in symbols:
            i = index_of[s.ticker].get(day)
            if i is None:
                r.unranked.append(Unranked(s.ticker, "no_bar"))
                continue
            value = s.score[i]
            if value is None or not math.isfinite(value):
                r.unranked.append(Unranked(s.ticker, "unknown"))
                continue
            if weighting == "inverse_volatility":
                assert s.vol is not None
                v = s.vol[i]
                if v is None or not math.isfinite(v) or v <= 0:
                    r.unranked.append(Unranked(s.ticker, "volatility_unknown"))
                    continue
                vols[s.ticker] = v
            known.append((s.ticker, value))
        known.sort(key=lambda kv: (-kv[1], kv[0]))
        r.ranked = [RankEntry(t, v, k + 1) for k, (t, v) in enumerate(known)]
        rank = {e.ticker: e.rank for e in r.ranked}
        flag = cash_filter.get(day) if cash_filter is not None else False
        r.cash_filter = flag if cash_filter is not None else None
        if cash_filter is not None and flag is None:
            counters["filter_unknown"] += 1
        if flag:
            target: list[str] = []
        else:
            kept = [t for t in held if t in rank and rank[t] <= top_n + buffer]
            target = list(kept)
            for e in r.ranked:
                if len(target) >= top_n:
                    break
                if e.ticker not in target:
                    target.append(e.ticker)
        target = sorted(target, key=lambda t: rank.get(t, 10**9))
        r.target = target
        r.exited = [t for t in held if t not in target]
        r.entered = [t for t in target if t not in holdings]
        weights = _weights(target, top_n, weighting, vols)
        r.weights = {t: weights[t] for t in target}
        index = len(rebalances)
        rebalances.append(r)
        reason = "cash_filter" if flag else "rebalance"
        for t in r.exited:
            pending[t] = _Order("exit", day, index, reason=reason)
        for t in target:
            pending[t] = _Order("target", day, index, weight=weights[t])

    for day in timeline:
        todays = [
            (s, index_of[s.ticker][day])
            for s in symbols
            if day in index_of[s.ticker] and index_of[s.ticker][day] >= s.first
        ]
        # Sells first (exits and trims), then buys (entries and top-ups).
        for s, i in todays:
            order = pending.get(s.ticker)
            if order is None or day <= order.signal_date:
                continue
            h = holdings.get(s.ticker)
            if order.kind == "exit":
                del pending[s.ticker]
                if h is not None:
                    sell(s, i, order, h.quantity, order.reason)
            elif h is not None:
                excess = h.quantity - target_quantity(s, i, order)
                if excess > 0:
                    del pending[s.ticker]
                    sell(s, i, order, excess, "resize")
        for s, i in sorted(todays, key=lambda si: _order_rank(pending.get(si[0].ticker))):
            order = pending.get(s.ticker)
            if order is None or day <= order.signal_date:
                continue
            del pending[s.ticker]
            h = holdings.get(s.ticker)
            need = target_quantity(s, i, order) - (h.quantity if h is not None else Decimal(0))
            if need > 0:
                buy(s, i, order, need)
        for s in symbols:
            i = index_of[s.ticker].get(day)
            if i is None:
                continue
            last_close[s.ticker] = s.close[i]
            h = holdings.get(s.ticker)
            if h is not None and i >= s.first:
                h.bars_held += 1
        if day in window_days:
            curve.append((day, ledger.equity(dict(last_close))))
        if day in signal_set:
            decide(day)

    for ticker, h in sorted(holdings.items()):
        s = by_ticker[ticker]
        close = last_close[ticker]
        trades.append(_trade(ticker, h, h.quantity, h.fees, s.dates[-1], close, close,
                             Decimal(0), "end_of_data", open_=True))  # fmt: skip

    navs = [nav for _, nav in curve]
    final = navs[-1] if navs else initial_cash
    bench_return, bench_final = _benchmark(symbols, initial_cash, costs, commission_bps)
    trades.sort(key=lambda t: (t.entry_date, t.ticker))
    return RotationResult(
        trades=trades,
        rebalances=rebalances,
        equity_curve=curve,
        final_nav=final,
        total_return=float((final - initial_cash) / initial_cash),
        sharpe=_sharpe(navs, risk_free_rate=risk_free_rate),
        max_drawdown=_max_drawdown(navs),
        total_fees=ledger.fees_paid.quantize(MICROS),
        price_costs=price_costs.quantize(MICROS),
        benchmark_return=bench_return,
        benchmark_final_nav=bench_final,
        fee_versions=dict(sorted(fee_versions.items())),
        fills_before_coverage=counters["before"],
        partial_entries=counters["partial"],
        adv_unknown=counters["adv_unknown"],
        cash_filter_unknown=counters["filter_unknown"],
        unfilled_at_end=len(pending),
    )


def _order_rank(order: _Order | None) -> tuple[int, float]:
    """Buys in weight order, largest first (equal weights keep universe order)."""
    if order is None:
        return (1, 0.0)
    return (0, -order.weight)


def _trade(
    ticker: str,
    h: _Holding,
    quantity: Decimal,
    entry_fees: Decimal,
    exit_date: date,
    exit_price: Decimal,
    exit_reference: Decimal,
    exit_fees: Decimal,
    reason: str,
    *,
    open_: bool,
    exit_adv_pct: float | None = None,
) -> RotationTrade:
    """``quantity`` of the holding, closed (or marked, ``open_``) at ``exit_price``;
    entry at the holding's average fill price with its share of the entry fees."""
    pnl = ((exit_price - h.price) * quantity - entry_fees - exit_fees).quantize(MICROS)
    notional = h.price * quantity
    return RotationTrade(
        ticker=ticker,
        entry_date=h.entry_date,
        entry_price=h.price,
        entry_reference=h.reference,
        exit_date=exit_date,
        exit_price=exit_price,
        exit_reference=exit_reference,
        quantity=quantity,
        entry_fees=entry_fees,
        exit_fees=exit_fees,
        pnl=pnl,
        return_pct=float(pnl / notional) if notional else 0.0,
        reason=reason,  # type: ignore[arg-type]
        open=open_,
        bars_held=h.bars_held,
        requested_quantity=h.requested,
        exit_adv_pct=exit_adv_pct,
    )


def _benchmark(
    symbols: list[RotationSymbol], cash: Decimal, costs: CostModel, commission_bps: Decimal
) -> tuple[float, Decimal]:
    """Equal-weight buy and hold of the universe from each symbol's first window close."""
    live = [s for s in symbols if len(s.dates) > s.first and s.close[s.first] > 0]
    if not live:
        return 0.0, cash
    share = cash / len(live)
    final = Decimal(0)
    for s in live:
        price = cost_adjusted(s.close[s.first], OrderSide.BUY, costs)
        shares = share / (price * (Decimal(1) + commission_bps / 10_000))
        final += shares * s.close[-1]
    return float((final - cash) / cash), final.quantize(MICROS)


__all__ = [
    "VOL_WINDOW",
    "RankEntry",
    "Rebalance",
    "RotationError",
    "RotationResult",
    "RotationSymbol",
    "RotationTrade",
    "Unranked",
    "last_session_of_period",
    "rebalance_signals",
    "run_rotation",
]
