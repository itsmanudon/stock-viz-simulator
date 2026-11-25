"""The backtester on the Rule DSL (A4.1, M7.1). Pure: arrays in, result out.

:func:`run_strategy` takes, per symbol, its daily bars (``Decimal`` OHLC),
the entry and exit rules' vector-mode signals (``True`` / ``False`` /
``None`` = unknown) and the ATR series the stops need, and replays them bar
by bar over the union of the symbols' dates. ``strategy_run.py`` loads those
from the database.

**Orders.** A signal is known at a bar's close, so its order fills on the
symbol's next bar under the run's profile (``next_open``: that bar's open;
``next_close``: its close), through :func:`fills.book` (the kernel and
``SimLedger``). An unknown signal does nothing and is counted. An entry
signal while the symbol is held is ignored (no pyramiding); a basket takes
entries in universe order while a slot is free.

**Stops** (any combination) rest from the entry fill: a fixed % and an ATR
multiple (both fixed at entry), a trailing stop (% or ATR below the highest
high since entry, updated after each close and used from the next bar) and
a time stop (an exit order after the position has seen ``N`` closes, the
entry bar's included). Price stops go through the kernel's
``evaluate_range_stop``: a bar that opens through the stop fills at the open
(``gap``), else a low (a high, short) through it fills at the stop.

**Priority within a bar** (:data:`STOP_PRIORITY`): (1) at the open, a stop
the open gapped through; (2) at the open (``next_open``), a pending exit
order (exit rule or time stop); (3) during the bar, the price stop nearest
the open is the first one the price reaches: the highest stop for a long,
the lowest for a short (ties: fixed, then ATR, then trailing); (4) at the
close (``next_close``), a pending exit order. After ``next_open`` entries the
entry bar's range can already hit the stop (the open came first); after
``next_close`` entries stops start on the next bar.

**Sizing.** Whole shares, never more than the free cash (fees included):
``all_in`` spends the free cash (a basket: free cash / free slots);
``fixed_fraction`` a fraction of equity; ``fixed_risk`` sizes so that the
initial stop costs ``risk_pct`` % of equity (distance from the expected
fill to the tightest initial price stop x quantity). Equity is the previous
close's mark. **R** = the trade's net P&L / its initial risk (quantity x
|entry fill - initial stop|), whenever the trade had a price stop.

Positions still open at the end are marked at the last close
(``end_of_data``, ``open``), not sold.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from stockviz.services.backtest.engine import (
    DEFAULT_RISK_FREE_RATE,
    _max_drawdown,
    _sharpe,
)
from stockviz.services.backtest.fills import BookedFill, book
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
STOP_KINDS = ("stop_fixed", "stop_atr", "trail")

STOP_PRIORITY = (
    "Within a bar: (1) a stop the open gapped through fills at the open; "
    "(2) a pending exit order (exit rule or time stop) fills at the open under next_open; "
    "(3) the price stop nearest the open fills at its level when the bar's low "
    "(high, for a short) reaches it: the highest stop for a long, the lowest for a short, "
    "ties fixed then ATR then trailing; (4) a pending exit order fills at the close under "
    "next_close."
)


@dataclass(frozen=True)
class SymbolInput:
    ticker: str
    dates: list[date]
    ts: list[datetime]
    """Aware instants per bar (the kernel's ``observed_at``)."""
    open: list[Decimal]
    high: list[Decimal]
    low: list[Decimal]
    close: list[Decimal]
    volume: list[Decimal]
    entry: list[bool | None]
    exit: list[bool | None] | None
    atr: dict[int, list[float | None]] = field(default_factory=dict)
    first: int = 0
    """Index of the first bar in the window; earlier bars are warm-up."""


@dataclass(frozen=True)
class Stops:
    fixed_pct: float | None = None
    atr_multiple: float | None = None
    atr_period: int = 14
    trail_kind: str | None = None  # "atr" | "pct"
    trail_value: float | None = None
    trail_period: int = 14
    time_bars: int | None = None

    @property
    def has_price_stop(self) -> bool:
        return (
            self.fixed_pct is not None
            or self.atr_multiple is not None
            or self.trail_kind is not None
        )

    def atr_periods(self) -> set[int]:
        out: set[int] = set()
        if self.atr_multiple is not None:
            out.add(self.atr_period)
        if self.trail_kind == "atr":
            out.add(self.trail_period)
        return out


@dataclass(frozen=True)
class Sizing:
    kind: str = "all_in"
    fraction: float | None = None
    risk_pct: float | None = None
    max_positions: int | None = None


@dataclass(frozen=True)
class StrategyTrade:
    ticker: str
    direction: str
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
    reason: str
    gap: bool
    open: bool
    bars_held: int
    initial_stop: Decimal | None
    initial_risk: Decimal | None
    r_multiple: float | None


@dataclass
class SymbolStats:
    ticker: str
    bars: int
    warmup_bars: int
    unknown_entry_bars: int = 0
    unknown_exit_bars: int = 0
    trades: int = 0


@dataclass(frozen=True)
class StrategyResult:
    trades: list[StrategyTrade]
    equity_curve: list[tuple[date, Decimal]]
    final_nav: Decimal
    total_return: float
    sharpe: float
    max_drawdown: float
    total_fees: Decimal
    price_costs: Decimal
    benchmark_return: float
    benchmark_final_nav: Decimal
    symbols: list[SymbolStats]
    ignored_entry_signals: int
    skip_reasons: dict[str, int]

    @property
    def gross_final_nav(self) -> Decimal:
        return self.final_nav + self.total_fees + self.price_costs

    @property
    def total_costs(self) -> Decimal:
        return (self.total_fees + self.price_costs).quantize(MICROS)


class StrategyError(ValueError):
    """The strategy cannot run on this data (a 400)."""


@dataclass
class _Position:
    quantity: Decimal
    entry_index: int
    entry_date: date
    entry_ts: datetime
    entry: BookedFill
    fixed: Decimal | None
    atr_stop: Decimal | None
    trail: Decimal | None
    extreme: Decimal
    """Highest high (long) or lowest low (short) since entry."""
    initial_stop: Decimal | None
    bars_held: int = 0


@dataclass
class _State:
    position: _Position | None = None
    pending: str | None = None  # "entry" | "exit_rule" | "time"
    signal_index: int = -1
    last_close: Decimal | None = None


def _dec(value: float) -> Decimal:
    return Decimal(repr(value)).quantize(MICROS)


def _known(values: list[float | None], i: int) -> float | None:
    if i < 0 or i >= len(values):
        return None
    v = values[i]
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else v


def run_strategy(
    symbols: list[SymbolInput],
    *,
    initial_cash: Decimal,
    stops: Stops,
    sizing: Sizing,
    profile: ExecutionProfile = NEXT_OPEN,
    costs: CostModel | None = None,
    schedule: FeeSchedule,
    commission_bps: Decimal = Decimal(0),
    short: bool = False,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
) -> StrategyResult:
    if initial_cash <= 0:
        raise StrategyError("initial_cash must be positive")
    if profile not in (NEXT_OPEN, LEGACY_CLOSE):
        raise StrategyError(f"unsupported profile {profile.name}")
    if sizing.kind == "fixed_risk" and not stops.has_price_stop:
        raise StrategyError("fixed_risk sizing needs a fixed, ATR or trailing stop")
    costs = costs or CostModel()
    at_open = profile == NEXT_OPEN
    entry_side = OrderSide.SELL if short else OrderSide.BUY
    exit_side = OrderSide.BUY if short else OrderSide.SELL
    max_positions = sizing.max_positions or len(symbols)

    ledger = SimLedger(cash=initial_cash)
    states = {s.ticker: _State() for s in symbols}
    index_of = [{d: i for i, d in enumerate(s.dates)} for s in symbols]
    stats = [
        SymbolStats(s.ticker, bars=len(s.dates) - s.first, warmup_bars=s.first) for s in symbols
    ]
    trades: list[StrategyTrade] = []
    skips = {"no_slot": 0, "no_cash": 0, "atr_unknown": 0}
    ignored = 0
    price_costs = Decimal(0)
    equity_mark = initial_cash
    curve: list[tuple[date, Decimal]] = []

    def free_slots() -> int:
        busy = sum(1 for st in states.values() if st.position is not None or st.pending == "entry")
        return max_positions - busy

    def snapshot(s: SymbolInput, i: int) -> MarketSnapshot:
        return MarketSnapshot(
            ticker=s.ticker,
            observed_at=s.ts[i],
            interval="1d",
            open=s.open[i],
            high=s.high[i],
            low=s.low[i],
            close=s.close[i],
            volume=s.volume[i],
        )

    def stop_levels(pos: _Position) -> list[tuple[Decimal, str]]:
        return [
            (level, kind)
            for level, kind in zip((pos.fixed, pos.atr_stop, pos.trail), STOP_KINDS, strict=True)
            if level is not None
        ]

    def effective(pos: _Position) -> tuple[Decimal, str] | None:
        levels = stop_levels(pos)
        if not levels:
            return None
        best = levels[0]
        for level, kind in levels[1:]:
            if (level > best[0]) if not short else (level < best[0]):
                best = (level, kind)
        return best

    def gapped(level: Decimal, open_: Decimal) -> bool:
        return open_ >= level if short else open_ <= level

    def record_exit(s: SymbolInput, k: int, i: int, fill: BookedFill, reason: str, gap: bool):
        nonlocal price_costs
        st = states[s.ticker]
        pos = st.position
        assert pos is not None
        price_costs += abs(fill.price - fill.reference) * pos.quantity
        trades.append(_trade(s.ticker, pos, s.dates[i], fill.price, fill.reference,
                             fill.fees.total, reason, gap, open_=False))  # fmt: skip
        stats[k].trades += 1
        st.position = None
        st.pending = None

    def exit_market(s: SymbolInput, k: int, i: int, reason: str) -> None:
        st = states[s.ticker]
        pos = st.position
        assert pos is not None
        order = OrderIntent(
            ticker=s.ticker,
            side=exit_side,
            order_type=SimulationOrderType.MARKET,
            quantity=pos.quantity,
            submitted_at=s.ts[st.signal_index],
        )
        fill = book(ledger, order, snapshot(s, i), profile, costs=costs, schedule=schedule,
                    commission_bps=commission_bps, short=short)  # fmt: skip
        assert fill is not None, "a market exit always fills"
        record_exit(s, k, i, fill, reason, gap=False)

    def try_stop(s: SymbolInput, k: int, i: int, *, gap_only: bool) -> bool:
        st = states[s.ticker]
        pos = st.position
        assert pos is not None
        eff = effective(pos)
        if eff is None:
            return False
        level, kind = eff
        bar = snapshot(s, i)
        if gap_only and not gapped(level, bar.open):
            return False
        order = OrderIntent(
            ticker=s.ticker,
            side=exit_side,
            order_type=SimulationOrderType.STOP_LOSS,
            quantity=pos.quantity,
            submitted_at=min(pos.entry_ts, s.ts[i]),
            limit_price=level,
        )
        fill = book(ledger, order, bar, profile, costs=costs, schedule=schedule,
                    commission_bps=commission_bps, range_stop=True, short=short)  # fmt: skip
        if fill is None:
            return False
        record_exit(s, k, i, fill, kind, gap=gapped(level, bar.open))
        return True

    def enter(s: SymbolInput, i: int) -> None:
        nonlocal price_costs
        st = states[s.ticker]
        j = st.signal_index
        st.pending = None
        reference = s.open[i] if at_open else s.close[i]
        expected = cost_adjusted(reference, entry_side, costs)
        if expected <= 0:
            skips["no_cash"] += 1
            return
        fixed = atr_stop = trail = None
        sign = Decimal(1) if short else Decimal(-1)
        if stops.fixed_pct is not None:
            fixed = (expected * (1 + sign * _dec(stops.fixed_pct) / 100)).quantize(MICROS)
        if stops.atr_multiple is not None:
            atr = _known(s.atr.get(stops.atr_period, []), j)
            if atr is None:
                skips["atr_unknown"] += 1
                return
            atr_stop = (expected + sign * _dec(stops.atr_multiple * atr)).quantize(MICROS)
        if stops.trail_kind is not None:
            assert stops.trail_value is not None
            if stops.trail_kind == "pct":
                trail = (expected * (1 + sign * _dec(stops.trail_value) / 100)).quantize(MICROS)
            else:
                atr = _known(s.atr.get(stops.trail_period, []), j)
                if atr is None:
                    skips["atr_unknown"] += 1
                    return
                trail = (expected + sign * _dec(stops.trail_value * atr)).quantize(MICROS)
        levels = [v for v in (fixed, atr_stop, trail) if v is not None and v > 0]
        initial = (min(levels) if short else max(levels)) if levels else None

        cash = ledger.cash
        if sizing.kind == "all_in":
            held = sum(1 for st in states.values() if st.position is not None)
            budget = cash / max(max_positions - held, 1)
        elif sizing.kind == "fixed_fraction":
            assert sizing.fraction is not None
            budget = min(cash, equity_mark * _dec(sizing.fraction))
        else:
            budget = cash
        quantity = (budget / expected).to_integral_value(rounding=ROUND_FLOOR)
        if sizing.kind == "fixed_risk":
            assert sizing.risk_pct is not None
            if initial is None or initial == expected:
                skips["no_cash"] += 1
                return
            risk = equity_mark * _dec(sizing.risk_pct) / 100
            by_risk = (risk / abs(expected - initial)).to_integral_value(rounding=ROUND_FLOOR)
            quantity = min(quantity, by_risk)
        # Fees come out of the same cash: shave whole shares until it fits.
        while quantity > 0:
            fee = schedule.fees(entry_side, quantity, expected, commission_bps=commission_bps).total
            if (expected * quantity + fee) <= cash:
                break
            short_by = (expected * quantity + fee - cash) / expected
            quantity -= max(Decimal(1), short_by.to_integral_value(rounding=ROUND_CEILING))
        if quantity <= 0:
            skips["no_cash"] += 1
            return
        order = OrderIntent(
            ticker=s.ticker,
            side=entry_side,
            order_type=SimulationOrderType.MARKET,
            quantity=quantity,
            submitted_at=s.ts[j],
        )
        try:
            fill = book(ledger, order, snapshot(s, i), profile, costs=costs, schedule=schedule,
                        commission_bps=commission_bps, short=short)  # fmt: skip
        except SimInsufficientCash:
            skips["no_cash"] += 1
            return
        assert fill is not None, "a market entry always fills"
        price_costs += abs(fill.price - fill.reference) * quantity
        st.position = _Position(
            quantity=quantity,
            entry_index=i,
            entry_date=s.dates[i],
            entry_ts=s.ts[i],
            entry=fill,
            fixed=fixed,
            atr_stop=atr_stop,
            trail=trail,
            extreme=fill.price,
            initial_stop=initial,
        )

    def signals_at_close(s: SymbolInput, k: int, i: int, candidates: list[int]) -> None:
        nonlocal ignored
        st = states[s.ticker]
        pos = st.position
        in_window = i >= s.first
        if pos is not None:
            pos.bars_held += 1
            extreme = s.low[i] if short else s.high[i]
            pos.extreme = min(pos.extreme, extreme) if short else max(pos.extreme, extreme)
            if stops.trail_kind is not None and pos.trail is not None:
                assert stops.trail_value is not None
                sign = Decimal(1) if short else Decimal(-1)
                level: Decimal | None
                if stops.trail_kind == "pct":
                    level = pos.extreme * (1 + sign * _dec(stops.trail_value) / 100)
                else:
                    atr = _known(s.atr.get(stops.trail_period, []), i)
                    level = (
                        None if atr is None else pos.extreme + sign * _dec(stops.trail_value * atr)
                    )
                if level is not None:
                    level = level.quantize(MICROS)
                    pos.trail = min(pos.trail, level) if short else max(pos.trail, level)
            ex = s.exit[i] if s.exit is not None else False
            if ex is None:
                stats[k].unknown_exit_bars += 1
            if s.entry[i] is True:
                ignored += 1
            if ex is True:
                st.pending, st.signal_index = "exit_rule", i
            elif stops.time_bars is not None and pos.bars_held >= stops.time_bars:
                st.pending, st.signal_index = "time", i
            return
        en = s.entry[i]
        if en is None:
            if in_window:
                stats[k].unknown_entry_bars += 1
        elif en:
            candidates.append(k)
            st.signal_index = i

    def take(candidates: list[int]) -> None:
        for k in candidates:
            if free_slots() <= 0:
                skips["no_slot"] += 1
                states[symbols[k].ticker].signal_index = -1
                continue
            states[symbols[k].ticker].pending = "entry"

    # A signal on the last warm-up bar fills on the window's first bar.
    warm: list[int] = []
    for k, s in enumerate(symbols):
        if s.first > 0:
            states[s.ticker].last_close = s.close[s.first - 1]
            signals_at_close(s, k, s.first - 1, warm)
    take(warm)

    calendar = sorted({d for s in symbols for d in s.dates[s.first :]})
    for day in calendar:
        candidates: list[int] = []
        for k, s in enumerate(symbols):
            i = index_of[k].get(day)
            if i is None or i < s.first:
                continue
            st = states[s.ticker]
            if st.position is not None:
                done = try_stop(s, k, i, gap_only=True)
                if not done and st.pending in ("exit_rule", "time") and at_open:
                    exit_market(s, k, i, st.pending)
                    done = True
                if not done:
                    done = try_stop(s, k, i, gap_only=False)
                if not done and st.pending in ("exit_rule", "time"):
                    exit_market(s, k, i, st.pending)
            elif st.pending == "entry":
                enter(s, i)
                if st.position is not None and at_open:
                    try_stop(s, k, i, gap_only=False)
            st.last_close = s.close[i]
            if i < len(s.dates) - 1:
                signals_at_close(s, k, i, candidates)
            elif st.position is not None:
                st.position.bars_held += 1
        take(candidates)
        closes = {t: st.last_close for t, st in states.items() if st.last_close is not None}
        equity_mark = ledger.equity(closes)  # type: ignore[arg-type]
        curve.append((day, equity_mark))

    for k, s in enumerate(symbols):
        st = states[s.ticker]
        if st.position is not None and st.last_close is not None:
            last = len(s.dates) - 1
            trades.append(_trade(s.ticker, st.position, s.dates[last], st.last_close,
                                 st.last_close, Decimal(0), "end_of_data", False, open_=True))  # fmt: skip
            stats[k].trades += 1

    navs = [nav for _, nav in curve]
    final = navs[-1] if navs else initial_cash
    bench_return, bench_final = _benchmark(symbols, initial_cash, costs, commission_bps)
    trades.sort(key=lambda t: (t.entry_date, t.ticker))
    return StrategyResult(
        trades=trades,
        equity_curve=curve,
        final_nav=final,
        total_return=float((final - initial_cash) / initial_cash),
        sharpe=_sharpe(navs, risk_free_rate=risk_free_rate),
        max_drawdown=_max_drawdown(navs),
        total_fees=ledger.fees_paid.quantize(MICROS),
        price_costs=price_costs.quantize(MICROS),
        benchmark_return=bench_return,
        benchmark_final_nav=bench_final,
        symbols=stats,
        ignored_entry_signals=ignored,
        skip_reasons={k: v for k, v in skips.items() if v},
    )


def _trade(
    ticker: str,
    pos: _Position,
    exit_date: date,
    exit_price: Decimal,
    exit_reference: Decimal,
    exit_fees: Decimal,
    reason: str,
    gap: bool,
    *,
    open_: bool,
) -> StrategyTrade:
    short = pos.entry.fill.side is OrderSide.SELL
    entry_price = pos.entry.price
    qty = pos.quantity
    gross = (entry_price - exit_price) * qty if short else (exit_price - entry_price) * qty
    pnl = (gross - pos.entry.fees.total - exit_fees).quantize(MICROS)
    notional = entry_price * qty
    risk = (
        (abs(entry_price - pos.initial_stop) * qty).quantize(MICROS)
        if pos.initial_stop is not None
        else None
    )
    return StrategyTrade(
        ticker=ticker,
        direction="short" if short else "long",
        entry_date=pos.entry_date,
        entry_price=entry_price,
        entry_reference=pos.entry.reference,
        exit_date=exit_date,
        exit_price=exit_price,
        exit_reference=exit_reference,
        quantity=qty,
        entry_fees=pos.entry.fees.total,
        exit_fees=exit_fees,
        pnl=pnl,
        return_pct=float(pnl / notional) if notional else 0.0,
        reason=reason,
        gap=gap,
        open=open_,
        bars_held=pos.bars_held,
        initial_stop=pos.initial_stop,
        initial_risk=risk,
        r_multiple=float(pnl / risk) if risk else None,
    )


def _benchmark(
    symbols: list[SymbolInput], cash: Decimal, costs: CostModel, commission_bps: Decimal
) -> tuple[float, Decimal]:
    """Equal-weight buy and hold from each symbol's first window close."""
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
    "STOP_PRIORITY",
    "Sizing",
    "Stops",
    "StrategyError",
    "StrategyResult",
    "StrategyTrade",
    "SymbolInput",
    "run_strategy",
]
