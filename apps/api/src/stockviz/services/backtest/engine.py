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


def _sharpe(navs: list[Decimal]) -> float:
    """Annualised Sharpe ratio of the daily NAV series (risk-free rate = 0)."""

    if len(navs) < 3:
        return 0.0
    returns: list[float] = []
    for prev, cur in pairwise(navs):
        if prev == 0:
            continue
        returns.append(float(cur / prev) - 1.0)
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
) -> BacktestResult:
    """Replay ``bars`` through ``strategy_type`` and return trades + equity curve.

    ``params`` carries the strategy-specific knobs:
      - ``rsi_threshold``: ``buy_below``, ``sell_above``
      - ``sma_crossover``: ``short_window``, ``long_window``
    """

    if initial_cash <= 0:
        raise BacktestError("initial_cash must be positive")

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

    for (ts, close), signal in zip(bars, signals, strict=True):
        if signal == "buy" and shares == 0 and cash > 0 and close > 0:
            shares = cash / close
            trades.append(BacktestTrade(date=ts.date(), side="buy", price=close, shares=shares))
            cash = Decimal(0)
        elif signal == "sell" and shares > 0:
            proceeds = shares * close
            trades.append(BacktestTrade(date=ts.date(), side="sell", price=close, shares=shares))
            cash = proceeds
            shares = Decimal(0)

        nav = cash + shares * close
        equity_curve.append(EquityPoint(date=ts.date(), nav=nav))

    navs = [pt.nav for pt in equity_curve]
    final_nav = navs[-1]
    total_return = float((final_nav - initial_cash) / initial_cash)
    summary = BacktestSummary(
        total_return=total_return,
        sharpe=_sharpe(navs),
        max_drawdown=_max_drawdown(navs),
        final_nav=final_nav,
    )
    return BacktestResult(trades=trades, equity_curve=equity_curve, summary=summary)
