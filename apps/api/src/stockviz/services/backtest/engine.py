"""Strategy backtesting over stored ``PriceBar`` history.

The engine is pure: it takes ``(timestamp, close)`` bars, an initial cash
amount and a strategy spec, and replays the bars day by day. No DB or network
access: the router loads bars and hands them in.

Since Phase 5.2 (SIM-08) fills come from the same kernel as live and replay
trading: each signal becomes an ``OrderIntent`` evaluated by
``services.simulation.evaluate_order`` on the next bar, and the fill is booked
in the shared ``SimLedger``. Costs (commission + slippage bps) are a fee on
each fill, never folded into the price. The profile is ``legacy_close`` (the
next bar's close); 5.3 adds the next-open fill rule.

Position model: a signal is **all-in** (cash into shares, rounded down to
6 places) or **all-out**. Bars before ``trade_from`` are warm-up only: signals
see them, but nothing trades, and neither the equity curve nor the benchmark
starts until the window does (audit SR-3).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import ROUND_DOWN, Decimal
from itertools import pairwise

from stockviz.services.indicators import compute_rsi, compute_sma
from stockviz.services.simulation import (
    LEGACY_CLOSE,
    FillStatus,
    MarketSnapshot,
    OrderIntent,
    OrderSide,
    SimInsufficientCash,
    SimLedger,
    SimulationOrderType,
    evaluate_order,
)

MICROS = Decimal("0.000001")
LEDGER_TICKER = "BACKTEST"

TRADING_DAYS_PER_YEAR = 252

DEFAULT_RISK_FREE_RATE = 0.05
"""Annual risk-free rate. Matches ``routers/trading.DEFAULT_RISK_FREE_RATE`` so
Sharpe is comparable between a backtest and the live portfolio analytics."""

DEFAULT_COMMISSION_BPS = 0.0
DEFAULT_SLIPPAGE_BPS = 0.0
"""Both default to zero so existing callers see unchanged numbers; the router
exposes them so a caller can model realistic frictions."""


@dataclass(frozen=True, slots=True)
class BacktestTrade:
    date: date
    side: str  # "buy" | "sell"
    price: Decimal
    shares: Decimal


@dataclass(frozen=True, slots=True)
class EquityPoint:
    date: date
    nav: Decimal


@dataclass(frozen=True, slots=True)
class BacktestSummary:
    total_return: float
    sharpe: float
    max_drawdown: float
    final_nav: Decimal
    # Buy-and-hold over the same window, for comparison. Without it there is
    # no way to tell whether a strategy beat doing nothing.
    benchmark_return: float = 0.0
    benchmark_final_nav: Decimal = Decimal(0)
    # Strategy return minus buy-and-hold return, in percentage points.
    excess_return: float = 0.0
    # Total commission + slippage paid across all fills.
    total_costs: Decimal = Decimal(0)


@dataclass(frozen=True, slots=True)
class BacktestResult:
    trades: list[BacktestTrade] = field(default_factory=list)
    equity_curve: list[EquityPoint] = field(default_factory=list)
    summary: BacktestSummary = field(
        default_factory=lambda: BacktestSummary(0.0, 0.0, 0.0, Decimal(0))
    )


class BacktestError(Exception):
    """Raised when a strategy spec is invalid for the given data."""


def _rsi_signals(
    bars: list[tuple[datetime, Decimal]], *, buy_below: float, sell_above: float
) -> list[str | None]:
    """Per-bar signal: ``"buy"`` when RSI < buy_below, ``"sell"`` when RSI > sell_above."""

    if not 0 <= buy_below <= 100 or not 0 <= sell_above <= 100:
        raise BacktestError("RSI thresholds must be between 0 and 100")
    if buy_below >= sell_above:
        raise BacktestError("buy_below must be less than sell_above")

    rsi_by_ts = {p.ts: p.value for p in compute_rsi(bars, period=14)}
    signals: list[str | None] = []
    for ts, _ in bars:
        rsi = rsi_by_ts.get(ts)
        if rsi is None:
            signals.append(None)
        elif rsi < buy_below:
            signals.append("buy")
        elif rsi > sell_above:
            signals.append("sell")
        else:
            signals.append(None)
    return signals


def _sma_crossover_signals(
    bars: list[tuple[datetime, Decimal]], *, short_window: int, long_window: int
) -> list[str | None]:
    """Per-bar signal: ``"buy"`` when the short SMA crosses above the long SMA, ``"sell"`` on the reverse."""

    if short_window <= 0 or long_window <= 0:
        raise BacktestError("SMA windows must be positive")
    if short_window >= long_window:
        raise BacktestError("short_window must be less than long_window")

    short_by_ts = {p.ts: p.value for p in compute_sma(bars, period=short_window)}
    long_by_ts = {p.ts: p.value for p in compute_sma(bars, period=long_window)}

    signals: list[str | None] = []
    prev_diff: float | None = None
    for ts, _ in bars:
        short = short_by_ts.get(ts)
        long = long_by_ts.get(ts)
        if short is None or long is None:
            signals.append(None)
            prev_diff = None
            continue
        diff = short - long
        if prev_diff is None:
            signals.append(None)
        elif prev_diff <= 0 < diff:
            signals.append("buy")
        elif prev_diff >= 0 > diff:
            signals.append("sell")
        else:
            signals.append(None)
        prev_diff = diff
    return signals


def _sharpe(navs: list[Decimal], *, risk_free_rate: float = DEFAULT_RISK_FREE_RATE) -> float:
    """Annualised Sharpe ratio of the daily NAV series.

    ``risk_free_rate`` is the annual figure, converted to a per-trading-day
    rate before being subtracted from each daily return. It defaults to the
    same constant the live portfolio analytics use, so a backtest and the
    portfolio page can't report different Sharpes for the same NAV series.
    """

    if len(navs) < 3:
        return 0.0
    daily_rf = risk_free_rate / TRADING_DAYS_PER_YEAR
    returns: list[float] = []
    for prev, cur in pairwise(navs):
        if prev == 0:
            continue
        returns.append(float(cur / prev) - 1.0 - daily_rf)
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    std = math.sqrt(variance)
    if std == 0:
        return 0.0
    return (mean / std) * math.sqrt(TRADING_DAYS_PER_YEAR)


def _max_drawdown(navs: list[Decimal]) -> float:
    """Largest peak-to-trough decline of the NAV series, as a positive fraction."""

    if not navs:
        return 0.0
    peak = navs[0]
    worst = 0.0
    for nav in navs:
        if nav > peak:
            peak = nav
        if peak > 0:
            drop = float((peak - nav) / peak)
            worst = max(worst, drop)
    return worst


RSI_WARMUP_BARS = 250
"""Wilder's RSI keeps a trace of every earlier bar; 250 bars (a year) makes the
first value in the window agree with a long history to well under 0.1."""


def warmup_bars_for(strategy_type: str, params: dict) -> int:
    """Bars before the window a strategy needs for its first real signal (SR-3)."""
    if strategy_type == "sma_crossover":
        return int(params["long_window"]) + 1  # one more bar to see the cross
    return RSI_WARMUP_BARS


def _aware(ts: datetime) -> datetime:
    return ts if ts.tzinfo is not None else ts.replace(tzinfo=UTC)


def _kernel_fill(
    side: OrderSide, quantity: Decimal, ts: datetime, close: Decimal
) -> Decimal | None:
    """The kernel's fill price for a market order on this bar, or None."""
    at = _aware(ts)
    decision = evaluate_order(
        OrderIntent(
            ticker=LEDGER_TICKER,
            side=side,
            order_type=SimulationOrderType.MARKET,
            quantity=quantity,
            remaining_quantity=quantity,
            submitted_at=at,
        ),
        MarketSnapshot(
            ticker=LEDGER_TICKER,
            observed_at=at,
            interval="1d",
            open=close,
            high=close,
            low=close,
            close=close,
            volume=Decimal(0),
        ),
        LEGACY_CLOSE,
    )
    return decision.fill_price if decision.status is FillStatus.FILLED else None


def run_backtest(
    bars: list[tuple[datetime, Decimal]],
    *,
    initial_cash: Decimal,
    strategy_type: str,
    params: dict,
    commission_bps: float = DEFAULT_COMMISSION_BPS,
    slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    trade_from: datetime | None = None,
    dividends: dict[date, Decimal] | None = None,
) -> BacktestResult:
    """Replay ``bars`` through ``strategy_type`` and return trades + equity curve.

    ``params`` carries the strategy-specific knobs:
      - ``rsi_threshold``: ``buy_below``, ``sell_above``
      - ``sma_crossover``: ``short_window``, ``long_window``

    Fills happen on the bar **after** the one that produced the signal: RSI(14)
    or an SMA cross is only knowable once that bar has closed, so filling at
    that same close would be look-ahead bias.

    ``trade_from``: bars before it are warm-up (SR-3). ``dividends`` (per-share
    amount by ex-date) turns on total return: shares held into an ex-date
    receive the dividend as cash, in the strategy and the benchmark alike
    (SR-7). Without it the result is price return.
    """

    if initial_cash <= 0:
        raise BacktestError("initial_cash must be positive")
    if commission_bps < 0 or slippage_bps < 0:
        raise BacktestError("commission_bps and slippage_bps must be non-negative")

    if strategy_type == "rsi_threshold":
        signals = _rsi_signals(bars, buy_below=params["buy_below"], sell_above=params["sell_above"])
    elif strategy_type == "sma_crossover":
        signals = _sma_crossover_signals(
            bars, short_window=params["short_window"], long_window=params["long_window"]
        )
    else:
        raise BacktestError(f"Unknown strategy type: {strategy_type!r}")

    first = 0
    if trade_from is not None:
        first = next((i for i, (ts, _) in enumerate(bars) if ts >= trade_from), len(bars))
    window = bars[first:]
    if not window:
        return BacktestResult(
            summary=BacktestSummary(
                total_return=0.0, sharpe=0.0, max_drawdown=0.0, final_nav=initial_cash
            )
        )

    ledger = SimLedger(cash=initial_cash)
    trades: list[BacktestTrade] = []
    equity_curve: list[EquityPoint] = []
    cost_rate = Decimal(str((commission_bps + slippage_bps) / 10_000.0))
    paid = dividends or {}

    def held() -> Decimal:
        position = ledger.positions.get(LEDGER_TICKER)
        return position.quantity if position is not None else Decimal(0)

    # A signal is only knowable once bar i has closed, so it fills on bar
    # i+1. A signal on the last warm-up bar fills on the window's first bar;
    # the final bar's signal is never acted on (no next bar).
    pending_signal = signals[first - 1] if first > 0 else None

    for offset, (ts, close) in enumerate(window):
        index = first + offset
        amount = paid.get(ts.date())
        if amount is not None and held() > 0:
            ledger.cash = (ledger.cash + (held() * amount).quantize(MICROS)).quantize(MICROS)

        signal = pending_signal
        if signal == "buy" and held() == 0 and ledger.cash > 0 and close > 0:
            quantity = (ledger.cash / (close * (Decimal(1) + cost_rate))).quantize(
                MICROS, rounding=ROUND_DOWN
            )
            price = _kernel_fill(OrderSide.BUY, quantity, ts, close) if quantity > 0 else None
            if price is not None:
                fees = (price * quantity * cost_rate).quantize(MICROS)
                try:
                    ledger.apply(OrderSide.BUY, LEDGER_TICKER, quantity, price, fees=fees)
                except SimInsufficientCash:  # rounding at the last micro-unit
                    quantity -= MICROS
                    fees = (price * quantity * cost_rate).quantize(MICROS)
                    ledger.apply(OrderSide.BUY, LEDGER_TICKER, quantity, price, fees=fees)
                trades.append(
                    BacktestTrade(date=ts.date(), side="buy", price=price, shares=quantity)
                )
        elif signal == "sell" and held() > 0:
            quantity = held()
            price = _kernel_fill(OrderSide.SELL, quantity, ts, close)
            if price is not None:
                fees = (price * quantity * cost_rate).quantize(MICROS)
                ledger.apply(OrderSide.SELL, LEDGER_TICKER, quantity, price, fees=fees)
                trades.append(
                    BacktestTrade(date=ts.date(), side="sell", price=price, shares=quantity)
                )

        equity_curve.append(EquityPoint(date=ts.date(), nav=ledger.equity({LEDGER_TICKER: close})))
        pending_signal = signals[index]

    navs = [pt.nav for pt in equity_curve]
    final_nav = navs[-1]
    total_return = float((final_nav - initial_cash) / initial_cash)

    # Buy-and-hold over the same window (from its first bar, not the warm-up),
    # with the same entry cost and, in total-return mode, the same dividends.
    first_close = window[0][1]
    last_close = window[-1][1]
    if first_close > 0:
        bh_shares = initial_cash / (first_close * (Decimal(1) + cost_rate))
        bh_income = sum(
            (bh_shares * amt for ts, _ in window[1:] if (amt := paid.get(ts.date())) is not None),
            Decimal(0),
        )
        benchmark_final = bh_shares * last_close + bh_income
        benchmark_return = float((benchmark_final - initial_cash) / initial_cash)
    else:
        benchmark_final = initial_cash
        benchmark_return = 0.0

    summary = BacktestSummary(
        total_return=total_return,
        sharpe=_sharpe(navs, risk_free_rate=risk_free_rate),
        max_drawdown=_max_drawdown(navs),
        final_nav=final_nav,
        benchmark_return=benchmark_return,
        benchmark_final_nav=benchmark_final,
        excess_return=(total_return - benchmark_return) * 100,
        total_costs=ledger.fees_paid,
    )
    return BacktestResult(trades=trades, equity_curve=equity_curve, summary=summary)
