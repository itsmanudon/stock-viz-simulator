"""Strategy backtesting over stored ``PriceBar`` history.

The engine is pure: it takes a list of ``(timestamp, close)`` bars, an initial
cash amount, and a strategy spec, and replays the bars day-by-day applying the
strategy's buy/sell signals. No DB or network access — the router loads bars
and hands them in.

Position model is deliberately simple: a signal is **all-in** (deploy all cash)
or **all-out** (liquidate the whole position). That keeps the equity curve
exactly reproducible by hand, which the issue's acceptance criteria require.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from itertools import pairwise

from stockviz.services.indicators import compute_rsi, compute_sma

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


def run_backtest(
    bars: list[tuple[datetime, Decimal]],
    *,
    initial_cash: Decimal,
    strategy_type: str,
    params: dict,
    commission_bps: float = DEFAULT_COMMISSION_BPS,
    slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
) -> BacktestResult:
    """Replay ``bars`` through ``strategy_type`` and return trades + equity curve.

    ``params`` carries the strategy-specific knobs:
      - ``rsi_threshold``: ``buy_below``, ``sell_above``
      - ``sma_crossover``: ``short_window``, ``long_window``

    Fills happen on the bar **after** the one that produced the signal: RSI(14)
    or an SMA cross is only knowable once that bar has closed, so filling at
    that same close would be look-ahead bias.

    ``commission_bps`` and ``slippage_bps`` are charged on both sides of every
    round trip. They default to zero, which reproduces a frictionless run.
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

    if not bars:
        return BacktestResult(
            summary=BacktestSummary(
                total_return=0.0, sharpe=0.0, max_drawdown=0.0, final_nav=initial_cash
            )
        )

    cash = initial_cash
    shares = Decimal(0)
    trades: list[BacktestTrade] = []
    equity_curve: list[EquityPoint] = []
    total_costs = Decimal(0)

    cost_rate = Decimal(str((commission_bps + slippage_bps) / 10_000.0))
    # A signal is only knowable once bar i has closed, so it can't be filled at
    # that same close — that would be look-ahead bias. Carry it to bar i+1 and
    # fill there. The final bar's signal is therefore never acted on, which is
    # correct: there is no next bar to trade into.
    pending_signal: str | None = None

    for ts, close in bars:
        signal = pending_signal
        if signal == "buy" and shares == 0 and cash > 0 and close > 0:
            # Slippage/commission make the effective purchase price worse.
            effective = close * (Decimal(1) + cost_rate)
            shares = cash / effective
            cost = cash - (shares * close)
            total_costs += cost
            trades.append(BacktestTrade(date=ts.date(), side="buy", price=close, shares=shares))
            cash = Decimal(0)
        elif signal == "sell" and shares > 0:
            gross = shares * close
            cost = gross * cost_rate
            total_costs += cost
            trades.append(BacktestTrade(date=ts.date(), side="sell", price=close, shares=shares))
            cash = gross - cost
            shares = Decimal(0)

        nav = cash + shares * close
        equity_curve.append(EquityPoint(date=ts.date(), nav=nav))
        pending_signal = signals[len(equity_curve) - 1]

    navs = [pt.nav for pt in equity_curve]
    final_nav = navs[-1]
    total_return = float((final_nav - initial_cash) / initial_cash)

    # Buy-and-hold over the same window and with the same entry cost.
    first_close = bars[0][1]
    last_close = bars[-1][1]
    if first_close > 0:
        bh_shares = initial_cash / (first_close * (Decimal(1) + cost_rate))
        benchmark_final = bh_shares * last_close
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
        total_costs=total_costs,
    )
    return BacktestResult(trades=trades, equity_curve=equity_curve, summary=summary)
