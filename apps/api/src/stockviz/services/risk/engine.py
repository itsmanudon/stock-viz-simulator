"""Historical-simulation VaR and CVaR, and a block-bootstrap Monte Carlo (Phase 8.3).

Pure functions over profit-and-loss scenarios, so the method can be checked
by hand. Conventions, stated where the numbers are shown (UX-9):

- **VaR** at confidence ``c`` over ``n`` scenarios is the ``k``-th largest
  loss, ``k = ceil(n x (1 - c))``: no more than ``1 - c`` of the scenarios
  lose more. With 500 scenarios at 95%, the 25th worst.
- **CVaR** (expected shortfall) is the mean of those ``k`` worst losses,
  VaR included, so it is never below VaR.
- Losses are positive numbers; a scenario that gains is a negative loss.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

VAR_METHOD = "historical_simulation"
MC_METHOD = "stationary_block_bootstrap"
CONFIDENCES: tuple[float, ...] = (0.95, 0.99)
HORIZONS: tuple[int, ...] = (1, 10)


@dataclass(frozen=True, slots=True)
class VarResult:
    confidence: float
    horizon_days: int
    scenarios: int
    tail_count: int
    var: float
    cvar: float


@dataclass(frozen=True, slots=True)
class MonteCarloResult:
    paths: int
    horizon_days: int
    mean_block: int
    seed: int
    percentiles: dict[int, float]
    """Ending value at percentile p, for p in 5, 25, 50, 75, 95."""
    prob_loss_10: float
    prob_loss_20: float
    goal: float | None = None
    """A target value (8.6), and the share of paths ending at or above it."""
    prob_goal: float | None = None


def tail_count(scenarios: int, confidence: float) -> int:
    # Round away float noise first: 500 x 0.05 is 25.000000000000004.
    return max(1, math.ceil(round(scenarios * (1 - confidence), 9)))


def historical_var(
    pnl: Sequence[float], *, confidence: float, horizon_days: int
) -> VarResult | None:
    """VaR and CVaR of a set of P&L scenarios (gains positive)."""
    if not pnl:
        return None
    losses = sorted((-x for x in pnl), reverse=True)
    k = tail_count(len(losses), confidence)
    tail = losses[:k]
    return VarResult(
        confidence=confidence,
        horizon_days=horizon_days,
        scenarios=len(losses),
        tail_count=k,
        var=tail[-1],
        cvar=sum(tail) / k,
    )


def compound_windows(returns: np.ndarray, horizon: int) -> np.ndarray:
    """Overlapping ``horizon``-session compounded returns, column by column.

    ``returns`` is (sessions x holdings) of simple daily returns; the result
    is ((sessions - horizon + 1) x holdings). Not the square-root-of-time
    rule: each window is a real run of history.
    """
    if horizon == 1:
        return returns
    growth = np.log1p(returns)
    cumulative = np.vstack([np.zeros((1, returns.shape[1])), np.cumsum(growth, axis=0)])
    return np.expm1(cumulative[horizon:] - cumulative[:-horizon])


def block_bootstrap(
    daily_returns: np.ndarray,
    *,
    start_value: float,
    paths: int = 10_000,
    horizon_days: int = 252,
    mean_block: int = 5,
    seed: int = 20261113,
    goal: float | None = None,
) -> MonteCarloResult:
    """Resample the portfolio's past daily returns in blocks of mean length 5.

    The stationary bootstrap (Politis and Romano): each step continues the
    current block with probability ``1 - 1/mean_block`` or jumps to a random
    day, wrapping at the end. Short runs of calm or stress stay together. A
    fixed seed makes the same request give the same answer.
    """
    n = len(daily_returns)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=paths)
    log_growth = np.zeros(paths)
    series = np.log1p(np.asarray(daily_returns, dtype=float))
    jump = 1.0 / mean_block
    for _ in range(horizon_days):
        log_growth += series[idx]
        restart = rng.random(paths) < jump
        idx = np.where(restart, rng.integers(0, n, size=paths), (idx + 1) % n)
    ending = start_value * np.exp(log_growth)
    return MonteCarloResult(
        paths=paths,
        horizon_days=horizon_days,
        mean_block=mean_block,
        seed=seed,
        percentiles={p: float(np.percentile(ending, p)) for p in (5, 25, 50, 75, 95)},
        prob_loss_10=float(np.mean(ending < start_value * 0.9)),
        prob_loss_20=float(np.mean(ending < start_value * 0.8)),
        goal=goal,
        prob_goal=float(np.mean(ending >= goal)) if goal is not None else None,
    )
