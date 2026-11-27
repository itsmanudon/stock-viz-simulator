"""The pairs lab (A9.3, M7.6): Engle-Granger cointegration on stored closes.

Two symbols' closes on their common dates, as logs.

1. **Hedge ratio** by OLS: ``ln A = alpha + beta ln B + e``.
2. **ADF on the residual** ``e``: ``de_t = gamma e_{t-1} + phi de_{t-1} + u``
   (one lag, no constant: the residual has mean zero by construction);
   ``tau`` = gamma / its standard error. It is compared with MacKinnon's (2010)
   critical values for the Engle-Granger test with **two variables and a
   constant**, adjusted for the sample size by his response surface
   ``b_inf + b1/T + b2/T^2``. Rejecting means the spread looks stationary.
3. **Half-life** of the spread: ``ln 2 / -lambda`` from ``de_t = c + lambda e_{t-1}``
   (null when lambda >= 0: no pull back).
4. **Z-score** of the latest spread over the window, and the **rolling hedge
   ratio** (``ROLLING`` sessions) to show whether beta is stable.

A test that does not reject is said plainly: two symbols can move together
without being cointegrated, and a cointegrated past is no promise.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

import numpy as np

ROLLING = 60
MIN_SESSIONS = 120

# MacKinnon (2010), Table 2: Engle-Granger tau, N = 2, constant ("c").
# (b_inf, b1, b2) at 1%, 5%, 10%.
MACKINNON_N2_C = {
    0.01: (-3.89644, -10.9519, -22.527),
    0.05: (-3.33613, -6.1101, -6.823),
    0.10: (-3.04445, -4.2412, -2.720),
}


def critical_values(n_obs: int) -> dict[float, float]:
    return {lvl: b0 + b1 / n_obs + b2 / n_obs**2 for lvl, (b0, b1, b2) in MACKINNON_N2_C.items()}


def ols(y: np.ndarray, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(coefficients, standard errors) of y on the columns of x."""
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    resid = y - x @ beta
    dof = max(len(y) - x.shape[1], 1)
    sigma2 = float(resid @ resid) / dof
    cov = sigma2 * np.linalg.inv(x.T @ x)
    return beta, np.sqrt(np.diag(cov))


def adf_tau(e: np.ndarray) -> float:
    de = np.diff(e)
    y = de[1:]
    x = np.column_stack([e[1:-1], de[:-1]])
    beta, se = ols(y, x)
    return float(beta[0] / se[0])


@dataclass
class Pair:
    a: str
    b: str
    sessions: int
    first: date | None = None
    last: date | None = None
    alpha: float | None = None
    beta: float | None = None
    tau: float | None = None
    critical: dict[str, float] = field(default_factory=dict)
    cointegrated_at: str | None = None
    half_life: float | None = None
    zscore: float | None = None
    rolling_beta: list[dict[str, object]] = field(default_factory=list)
    spread: list[dict[str, object]] = field(default_factory=list)
    reason: str | None = None


def pair_stats(a: str, b: str, rows: list[tuple[date, float, float]]) -> Pair:
    """``rows``: (date, close A, close B) on common dates, oldest first (pure)."""
    out = Pair(a=a, b=b, sessions=len(rows))
    if len(rows) < MIN_SESSIONS:
        out.reason = f"Needs {MIN_SESSIONS} sessions both symbols traded; found {len(rows)}."
        return out
    dates = [r[0] for r in rows]
    la = np.log(np.array([r[1] for r in rows]))
    lb = np.log(np.array([r[2] for r in rows]))
    out.first, out.last = dates[0], dates[-1]
    (alpha, beta), _se = ols(la, np.column_stack([np.ones_like(lb), lb]))
    e = la - alpha - beta * lb
    out.alpha, out.beta = round(float(alpha), 6), round(float(beta), 6)
    tau = adf_tau(e)
    out.tau = round(tau, 4)
    cv = critical_values(len(e))
    out.critical = {f"{int(k * 100)}%": round(v, 4) for k, v in cv.items()}
    for level in (0.01, 0.05, 0.10):
        if tau < cv[level]:
            out.cointegrated_at = f"{int(level * 100)}%"
            break
    (c, lam), _ = ols(np.diff(e), np.column_stack([np.ones(len(e) - 1), e[:-1]]))
    del c
    out.half_life = round(math.log(2) / -float(lam), 2) if lam < 0 else None
    sd = float(np.std(e, ddof=1))
    out.zscore = round(float((e[-1] - e.mean()) / sd), 3) if sd > 0 else None
    for end in range(ROLLING, len(rows) + 1, max(ROLLING // 3, 1)):
        window = slice(end - ROLLING, end)
        (_a, rb), _ = ols(la[window], np.column_stack([np.ones(ROLLING), lb[window]]))
        out.rolling_beta.append({"date": dates[end - 1], "beta": round(float(rb), 6)})
    step = max(len(e) // 250, 1)
    out.spread = [
        {"date": dates[i], "spread": round(float(e[i]), 6)} for i in range(0, len(e), step)
    ]
    return out
