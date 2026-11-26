"""The backtest report card and its overfitting checks (A4.3, M7.4). Pure.

Everything here works on a run's daily equity curve (net of every cost: the
NAV already paid fees, spread and slippage) and its round trips. Formulas,
as the API returns them in each metric's ``formula``:

- **Daily returns** ``r_t = NAV_t / NAV_{t-1} - 1``; excess returns
  ``e_t = r_t - rf / 252`` with the 5% annual risk-free rate the summary's
  Sharpe uses (``engine.DEFAULT_RISK_FREE_RATE``).
- **CAGR** ``(NAV_end / cash)^(1 / years) - 1``, ``years`` = calendar days from
  the first to the last curve date / 365.25.
- **Sortino** ``mean(e) / sqrt(mean(min(e, 0)^2)) x sqrt(252)`` (target 0 on
  excess returns, every day in the denominator's mean).
- **Calmar** ``CAGR / max drawdown``.
- **Win rate** closed trades with net P&L > 0 / closed trades. **Payoff
  ratio** mean winning P&L / |mean losing P&L|. **Profit factor** sum of
  winning P&L / |sum of losing P&L|. **Expectancy** mean net P&L per closed
  trade (money) and mean R over closed trades that had a price stop.
- **Exposure** share of the curve's sessions holding a position at the close.
  **Average holding** mean calendar days from entry to exit, closed trades.

Sharpe statistics (Bailey and López de Prado, "The Sharpe Ratio Efficient
Frontier", 2012, and "The Deflated Sharpe Ratio", 2014): ``SR`` is the
per-day Sharpe of the excess returns (mean / sample standard deviation), so
the annualised figure is ``SR x sqrt(252)``, the summary's Sharpe. ``g3`` is
the skewness and ``g4`` the kurtosis (not excess: 3 for a normal), both from
population moments; ``T`` the number of daily returns.

- **PSR** ``Phi((SR - SR*) sqrt(T - 1) / sqrt(1 - g3 SR + (g4 - 1) / 4 SR^2))``:
  the probability that the true Sharpe exceeds ``SR*`` (default 0).
- **Expected maximum Sharpe of N trials** (DSR paper, eq. 2):
  ``SR0 = sqrt(V) ((1 - gamma) Phi^-1(1 - 1/N) + gamma Phi^-1(1 - 1/(N e)))``,
  ``V`` the variance of the trials' per-day Sharpes, ``gamma`` the
  Euler-Mascheroni constant. **DSR** = PSR(SR0). With one trial there is no
  maximum to deflate: DSR = PSR(0).

PBO by combinatorially symmetric cross-validation (Bailey, Borwein, López de
Prado and Zhu, "The Probability of Backtest Overfitting", 2017): see
:func:`pbo_cscv`.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from itertools import combinations, pairwise
from statistics import NormalDist
from typing import Any

import numpy as np

from stockviz.services.backtest.engine import DEFAULT_RISK_FREE_RATE, TRADING_DAYS_PER_YEAR
from stockviz.services.risk.engine import MC_METHOD, stationary_indices

EULER_GAMMA = 0.5772156649015329
_NORMAL = NormalDist()

MC_PATHS = 2_000
MC_MEAN_BLOCK = 5
MC_SEED = 20261126
MC_POINTS = 60
MC_MIN_RETURNS = 20

PBO_BLOCKS = 16
PBO_MIN_ROWS_PER_BLOCK = 4

PLATEAU_TOLERANCE = 0.25
"""A neighbour holds up when its value is within 25% of the best's magnitude."""
PLATEAU_MIN_SHARE = 0.5

REGIME_ORDER = ("Calm trend", "Choppy", "High-vol down", None)


@dataclass(frozen=True)
class Trip:
    """One round trip: entry and exit dates, net P&L (both legs' fees), R."""

    entry_date: date
    exit_date: date
    pnl: Decimal
    r_multiple: float | None
    open: bool


# --- returns and Sharpe statistics -----------------------------------------


def nav_returns(navs: Sequence[Decimal]) -> list[float]:
    """Simple daily returns, the same arithmetic as ``engine._sharpe``."""
    out: list[float] = []
    for prev, cur in pairwise(navs):
        if prev == 0:
            continue
        out.append(float(cur / prev) - 1.0)
    return out


def excess(
    returns: Sequence[float],
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    periods_per_year: float = TRADING_DAYS_PER_YEAR,
) -> list[float]:
    daily_rf = risk_free_rate / periods_per_year
    return [r - daily_rf for r in returns]


def moments(values: Sequence[float]) -> tuple[float, float, float | None, float | None]:
    """Mean, sample standard deviation, skewness and kurtosis (population moments)."""
    n = len(values)
    if n == 0:
        return 0.0, 0.0, None, None
    mean = sum(values) / n
    if n < 2:
        return mean, 0.0, None, None
    dev = [v - mean for v in values]
    m2 = sum(d * d for d in dev) / n
    std = math.sqrt(sum(d * d for d in dev) / (n - 1))
    if m2 <= 0:
        return mean, std, None, None
    m3 = sum(d**3 for d in dev) / n
    m4 = sum(d**4 for d in dev) / n
    return mean, std, m3 / m2**1.5, m4 / m2**2


def psr(
    sharpe: float, benchmark: float, observations: int, skew: float, kurt: float
) -> float | None:
    """Probabilistic Sharpe ratio; per-period Sharpes. None when undefined."""
    if observations < 2:
        return None
    radicand = 1 - skew * sharpe + (kurt - 1) / 4 * sharpe**2
    if radicand <= 0:
        return None
    z = (sharpe - benchmark) * math.sqrt(observations - 1) / math.sqrt(radicand)
    return _NORMAL.cdf(z)


def expected_max_sharpe(trials: int, variance: float) -> float:
    """SR0: the expected maximum of ``trials`` Sharpes with true Sharpe 0."""
    if trials < 2 or variance <= 0:
        return 0.0
    a = _NORMAL.inv_cdf(1 - 1 / trials)
    b = _NORMAL.inv_cdf(1 - 1 / (trials * math.e))
    return math.sqrt(variance) * ((1 - EULER_GAMMA) * a + EULER_GAMMA * b)


@dataclass(frozen=True)
class SharpeStats:
    observations: int
    mean: float
    std: float
    sharpe: float
    """Per day."""
    skewness: float | None
    kurtosis: float | None
    psr: float | None
    """PSR against a benchmark Sharpe of 0."""
    periods_per_year: float = TRADING_DAYS_PER_YEAR
    """A6.4: return periods a year (252 sessions; an intraday run's bars a year)."""

    @property
    def sharpe_annual(self) -> float:
        return self.sharpe * math.sqrt(self.periods_per_year)


def sharpe_stats(
    returns: Sequence[float], periods_per_year: float = TRADING_DAYS_PER_YEAR
) -> SharpeStats:
    e = excess(returns, periods_per_year=periods_per_year)
    mean, std, skew, kurt = moments(e)
    sr = mean / std if std > 0 and len(e) >= 2 else 0.0
    value = psr(sr, 0.0, len(e), skew, kurt) if skew is not None and kurt is not None else None
    return SharpeStats(len(e), mean, std, sr, skew, kurt, value, periods_per_year)


def deflated(stats: SharpeStats, trials: int, variance: float | None) -> tuple[float, float | None]:
    """(SR0, DSR) for a run's Sharpe statistics, N trials and their variance."""
    sr0 = expected_max_sharpe(trials, variance or 0.0)
    if stats.skewness is None or stats.kurtosis is None:
        return sr0, None
    return sr0, psr(stats.sharpe, sr0, stats.observations, stats.skewness, stats.kurtosis)


# --- the metrics -----------------------------------------------------------

FORMULAS: dict[str, tuple[str, str, str]] = {
    # key: (label, unit, formula)
    "cagr": ("CAGR", "pct", "(final NAV / initial cash)^(365.25 / calendar days) - 1"),
    "sortino": (
        "Sortino",
        "ratio",
        "mean(e) / sqrt(mean(min(e, 0)^2)) x sqrt(252); e = daily return - 5%/252",
    ),
    "calmar": ("Calmar", "ratio", "CAGR / max drawdown"),
    "win_rate": ("Win rate", "pct", "closed trades with net P&L > 0 / closed trades"),
    "payoff_ratio": ("Payoff ratio", "ratio", "mean winning P&L / |mean losing P&L|"),
    "profit_factor": ("Profit factor", "ratio", "sum of winning P&L / |sum of losing P&L|"),
    "expectancy": ("Expectancy", "money", "mean net P&L per closed trade"),
    "expectancy_r": (
        "Expectancy (R)",
        "r",
        "mean R over closed trades with a price stop; R = net P&L / initial risk",
    ),
    "exposure": ("Exposure", "pct", "sessions holding a position at the close / sessions"),
    "avg_holding_days": (
        "Average holding",
        "days",
        "mean calendar days from entry to exit, closed trades",
    ),
    "closed_trades": ("Closed trades", "count", "round trips with an exit (open ones excluded)"),
}


def exposure_flags(dates: Sequence[date], trips: Sequence[Trip]) -> list[bool]:
    """Per curve date: a position was held at that session's close."""
    flags = [False] * len(dates)
    for t in trips:
        for i, d in enumerate(dates):
            if t.entry_date <= d and (d < t.exit_date or (t.open and d <= t.exit_date)):
                flags[i] = True
    return flags


def _metric(key: str, value: float | None, note: str | None = None) -> dict[str, Any]:
    label, unit, formula = FORMULAS[key]
    return {
        "key": key,
        "label": label,
        "value": value,
        "unit": unit,
        "formula": formula,
        "note": note if value is None else None,
    }


def metrics(
    curve: Sequence[tuple[date, Decimal]],
    trips: Sequence[Trip],
    initial_cash: Decimal,
    max_drawdown: float,
    periods_per_year: float = TRADING_DAYS_PER_YEAR,
) -> list[dict[str, Any]]:
    """The report card's metrics, each with its formula; null with a note when
    undefined. A6.4: an intraday curve (one point per bar, datetimes) passes
    its bars a year; holding is then fractional days."""
    dates = [d for d, _ in curve]
    navs = [n for _, n in curve]
    returns = nav_returns(navs)
    out: list[dict[str, Any]] = []

    cagr: float | None = None
    note = "Fewer than two sessions."
    if len(curve) >= 2 and (dates[-1] - dates[0]).days > 0 and initial_cash > 0:
        years = (dates[-1] - dates[0]).days / 365.25
        ratio = float(navs[-1] / initial_cash)
        cagr = ratio ** (1 / years) - 1 if ratio > 0 else -1.0
    out.append(_metric("cagr", cagr, note))

    e = excess(returns, periods_per_year=periods_per_year)
    sortino: float | None = None
    note = "Fewer than two daily returns."
    if len(e) >= 2:
        downside = math.sqrt(sum(min(x, 0.0) ** 2 for x in e) / len(e))
        if downside > 0:
            sortino = (sum(e) / len(e)) / downside * math.sqrt(periods_per_year)
        else:
            note = "No day fell below the risk-free rate."
    out.append(_metric("sortino", sortino, note))

    calmar = cagr / max_drawdown if cagr is not None and max_drawdown > 0 else None
    out.append(_metric("calmar", calmar, "No drawdown." if cagr is not None else "No CAGR."))

    closed = [t for t in trips if not t.open]
    wins = [t.pnl for t in closed if t.pnl > 0]
    losses = [t.pnl for t in closed if t.pnl < 0]
    none_closed = "No closed trades."
    out.append(_metric("win_rate", len(wins) / len(closed) if closed else None, none_closed))
    payoff = (
        float((sum(wins, Decimal(0)) / len(wins)) / abs(sum(losses, Decimal(0)) / len(losses)))
        if wins and losses
        else None
    )
    out.append(_metric("payoff_ratio", payoff, "Needs a winning and a losing trade."))
    factor = (
        float(sum(wins, Decimal(0)) / abs(sum(losses, Decimal(0)))) if losses and closed else None
    )
    out.append(_metric("profit_factor", factor, "No losing trades." if closed else none_closed))
    expectancy = float(sum((t.pnl for t in closed), Decimal(0)) / len(closed)) if closed else None
    out.append(_metric("expectancy", expectancy, none_closed))
    rs = [t.r_multiple for t in closed if t.r_multiple is not None]
    out.append(
        _metric(
            "expectancy_r",
            sum(rs) / len(rs) if rs else None,
            "No closed trade had a price stop, so R is not defined.",
        )
    )
    flags = exposure_flags(dates, trips)
    out.append(_metric("exposure", sum(flags) / len(flags) if flags else None, "No sessions."))
    holding = [(t.exit_date - t.entry_date).total_seconds() / 86400 for t in closed]
    out.append(
        _metric("avg_holding_days", sum(holding) / len(holding) if holding else None, none_closed)
    )
    out.append(_metric("closed_trades", float(len(closed)), None))
    return out


# --- Monte Carlo drawdown fan ----------------------------------------------


def mc_fan(
    returns: Sequence[float],
    dates: Sequence[date],
    start_value: float,
    *,
    paths: int = MC_PATHS,
    mean_block: int = MC_MEAN_BLOCK,
    seed: int = MC_SEED,
    points: int = MC_POINTS,
) -> dict[str, Any] | None:
    """Resample the run's daily net returns with the Phase 8 stationary block
    bootstrap (``risk.engine.stationary_indices``) for as many sessions as
    the run had: each path's maximum drawdown and its NAV at up to ``points``
    dates. ``dates`` are the curve's dates (one more than the returns)."""
    n = len(returns)
    if n < MC_MIN_RETURNS or start_value <= 0:
        return None
    series = np.log1p(np.asarray(returns, dtype=float))
    rng = np.random.default_rng(seed)
    log_value = np.zeros(paths)
    peak = np.zeros(paths)
    worst = np.zeros(paths)
    step = max(1, math.ceil(n / points))
    keep = set(range(step - 1, n, step)) | {n - 1}
    fan: list[dict[str, Any]] = [
        {"date": dates[0].isoformat(), "p5": start_value, "p50": start_value, "p95": start_value}
    ]
    for k, idx in enumerate(stationary_indices(n, paths=paths, horizon_days=n,
                                               mean_block=mean_block, rng=rng)):  # fmt: skip
        log_value += series[idx]
        peak = np.maximum(peak, log_value)
        worst = np.maximum(worst, 1 - np.exp(log_value - peak))
        if k in keep:
            values = start_value * np.exp(log_value)
            p5, p50, p95 = np.percentile(values, [5, 50, 95])
            fan.append(
                {
                    "date": dates[k + 1].isoformat(),
                    "p5": float(p5),
                    "p50": float(p50),
                    "p95": float(p95),
                }
            )
    final = start_value * np.exp(log_value)
    dd = np.percentile(worst, [5, 50, 95])
    fin = np.percentile(final, [5, 50, 95])
    return {
        "method": MC_METHOD,
        "paths": paths,
        "mean_block": mean_block,
        "seed": seed,
        "horizon_days": n,
        "max_drawdown": {"p5": float(dd[0]), "p50": float(dd[1]), "p95": float(dd[2])},
        "final_nav": {"p5": float(fin[0]), "p50": float(fin[1]), "p95": float(fin[2])},
        "prob_loss": float(np.mean(final < start_value)),
        "fan": fan,
    }


# --- regime split ----------------------------------------------------------


def regime_split(
    curve: Sequence[tuple[date, Decimal]],
    states: Sequence[str | None],
    trips: Sequence[Trip],
    periods_per_year: float = TRADING_DAYS_PER_YEAR,
) -> list[dict[str, Any]]:
    """Per regime state, the run's daily returns while it held. The return
    from session t-1 to t counts under the state known at t-1's close
    (``states[t - 1]``), so no day is classified with information from that
    day. ``states`` is aligned with ``curve``."""
    dates = [d for d, _ in curve]
    navs = [n for _, n in curve]
    flags = exposure_flags(dates, trips)
    groups: dict[str | None, list[int]] = {}
    for t in range(1, len(curve)):
        if navs[t - 1] == 0:
            continue
        groups.setdefault(states[t - 1], []).append(t)
    index_of = {d: i for i, d in enumerate(dates)}
    entered: dict[str | None, int] = {}
    for trip in trips:
        i = index_of.get(trip.entry_date)
        if i is not None and i > 0:
            entered[states[i - 1]] = entered.get(states[i - 1], 0) + 1
    total = sum(len(v) for v in groups.values())
    rows: list[dict[str, Any]] = []
    for state in REGIME_ORDER:
        days = groups.get(state, [])
        if not days:
            continue
        r = [float(navs[t] / navs[t - 1]) - 1.0 for t in days]
        growth = math.prod(1 + x for x in r) - 1
        stats = sharpe_stats(r, periods_per_year)
        rows.append(
            {
                "state": state,
                "sessions": len(days),
                "share": len(days) / total if total else 0.0,
                "return": growth,
                "sharpe": stats.sharpe_annual if len(r) >= 2 and stats.std > 0 else None,
                "exposure": sum(1 for t in days if flags[t - 1]) / len(days),
                "trades_entered": entered.get(state, 0),
            }
        )
    return rows


# --- PBO (CSCV) ------------------------------------------------------------


def _sharpe_rows(total: np.ndarray, sq: np.ndarray, count: np.ndarray) -> np.ndarray:
    count = count[:, None]
    mean = total / count
    var = np.maximum((sq - count * mean**2) / np.maximum(count - 1, 1), 0.0)
    std = np.sqrt(var)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(std > 1e-15, mean / std, 0.0)


def pbo_cscv(
    returns: np.ndarray, *, blocks: int = PBO_BLOCKS, min_rows: int = PBO_MIN_ROWS_PER_BLOCK
) -> dict[str, Any] | None:
    """Probability of backtest overfitting over a (T sessions x N settings)
    matrix of daily returns (Bailey, Borwein, López de Prado, Zhu 2017).

    1. Split the T rows into ``blocks`` (S, even) equal blocks of
       ``T // S`` rows, in time order; the oldest ``T mod S`` rows are dropped.
    2. For every one of the C(S, S/2) ways to pick S/2 blocks as the
       in-sample set J (the rest, J', is out of sample), find the setting
       with the best in-sample Sharpe (per day, mean / sample std; ties: the
       first) and its rank r among the N settings out of sample (1 = worst,
       ties averaged; Sharpes rounded to 10 decimals first).
    3. The relative rank is w = r / (N + 1) and the logit l = ln(w / (1 - w)).
       PBO is the share of combinations with l <= 0: the in-sample best did
       no better than the median out of sample.

    Returns None when there are fewer than two settings or too few rows."""
    t_rows, n = returns.shape
    if n < 2 or blocks < 2 or blocks % 2 or t_rows < blocks * min_rows:
        return None
    size = t_rows // blocks
    dropped = t_rows - size * blocks
    m = returns[dropped:].reshape(blocks, size, n)
    bsum = m.sum(axis=1)
    bsq = (m**2).sum(axis=1)
    bcnt = np.full(blocks, size, dtype=float)
    combos = list(combinations(range(blocks), blocks // 2))
    pick = np.zeros((len(combos), blocks))
    for k, c in enumerate(combos):
        pick[k, list(c)] = 1.0
    rest = 1.0 - pick
    # Rounded so that sums in another order cannot split a tie.
    train = np.round(_sharpe_rows(pick @ bsum, pick @ bsq, pick @ bcnt), 10)
    test = np.round(_sharpe_rows(rest @ bsum, rest @ bsq, rest @ bcnt), 10)
    best = np.argmax(train, axis=1)
    chosen = test[np.arange(len(combos)), best]
    below = (test < chosen[:, None]).sum(axis=1)
    ties = (test == chosen[:, None]).sum(axis=1) - 1
    rank = 1 + below + 0.5 * ties
    w = rank / (n + 1)
    logits = np.log(w / (1 - w))
    pbo = float(np.mean(logits <= 0))
    edges = np.arange(-4.0, 4.01, 0.5)
    clipped = np.clip(logits, -3.999, 3.999)
    counts, _ = np.histogram(clipped, bins=edges)
    return {
        "method": "cscv",
        "pbo": pbo,
        "blocks": blocks,
        "block_sessions": size,
        "dropped_sessions": dropped,
        "sessions": t_rows,
        "settings": n,
        "combinations": len(combos),
        "metric": "sharpe",
        "logit_median": float(np.median(logits)),
        "prob_oos_loss": float(np.mean(chosen < 0)),
        "histogram": [
            {"lo": float(lo), "hi": float(hi), "count": int(c)}
            for lo, hi, c in zip(edges[:-1], edges[1:], counts, strict=True)
        ],
        "logits": [float(x) for x in logits] if len(combos) <= 100 else None,
    }


# --- parameter plateau -----------------------------------------------------


def plateau(
    points: Sequence[tuple[float, float, float | None]],
    *,
    x_param: str,
    y_param: str,
    metric: str,
    tolerance: float = PLATEAU_TOLERANCE,
) -> dict[str, Any] | None:
    """A heatmap of ``metric`` over two parameters and whether the best cell
    sits on a plateau: its grid neighbours (up to 8 adjacent cells that were
    run) within ``tolerance`` x |best| of it. Fewer than half holding up, or
    no neighbours at all, is an isolated peak."""
    xs = sorted({p[0] for p in points})
    ys = sorted({p[1] for p in points})
    if len(xs) < 2 or len(ys) < 2:
        return None
    cell: dict[tuple[int, int], float] = {}
    for x, y, v in points:
        if v is not None and math.isfinite(v):
            cell[(xs.index(x), ys.index(y))] = v
    if not cell:
        return None
    (bi, bj), best = max(cell.items(), key=lambda kv: kv[1])
    margin = tolerance * abs(best)
    neighbours = [
        cell[(bi + di, bj + dj)]
        for di in (-1, 0, 1)
        for dj in (-1, 0, 1)
        if (di or dj) and (bi + di, bj + dj) in cell
    ]
    within = sum(1 for v in neighbours if v >= best - margin)
    share = within / len(neighbours) if neighbours else 0.0
    isolated = not neighbours or share < PLATEAU_MIN_SHARE
    return {
        "metric": metric,
        "x_param": x_param,
        "y_param": y_param,
        "x_values": xs,
        "y_values": ys,
        "cells": [[cell.get((i, j)) for i in range(len(xs))] for j in range(len(ys))],
        "best": {"x": xs[bi], "y": ys[bj], "value": best},
        "tolerance": tolerance,
        "neighbours": len(neighbours),
        "within": within,
        "share_within": share,
        "isolated": isolated,
        "rule": (
            f"Neighbours are the adjacent cells run; one holds up when it is within "
            f"{tolerance:.0%} of the best's magnitude. Fewer than half holding up is an "
            "isolated peak."
        ),
    }


__all__ = [
    "EULER_GAMMA",
    "FORMULAS",
    "MC_SEED",
    "SharpeStats",
    "Trip",
    "deflated",
    "excess",
    "expected_max_sharpe",
    "exposure_flags",
    "mc_fan",
    "metrics",
    "moments",
    "nav_returns",
    "pbo_cscv",
    "plateau",
    "psr",
    "regime_split",
    "sharpe_stats",
]
