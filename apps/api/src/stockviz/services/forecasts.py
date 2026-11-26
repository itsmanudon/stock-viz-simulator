"""Volatility forecasts and price cones, scored honestly (A9.2, M8.2, M8.3).

The phase's done-when: **each forecast shows its skill against a random walk
and its realised coverage.** Everything here is scored out of sample: a value
for day ``t`` uses only bars up to ``t``.

**HAR-RV** (Corsi 2009) on daily realised variance from the high and low
(Parkinson 1980: ``ln(H/L)^2 / (4 ln 2)``; daily bars have no intraday
returns). Tomorrow's variance is regressed on today's, the last 5 days' mean
and the last 22 days' mean, by ordinary least squares on every earlier day
(refit every ``REFIT_EVERY`` days). Over the last ``TEST_DAYS`` days its
one-day forecasts are compared with the random walk (tomorrow = today) by
mean squared error and QLIKE (``RV/F - ln(RV/F) - 1``, the loss robust to
noisy variance proxies, Patton 2011). Skill = 1 - loss(HAR) / loss(random walk):
above 0 beats the random walk.

**Conformal price cones** around a zero-drift random walk, for horizons of
1, 5 and 20 sessions: on each day the band is ``close x exp(+-q)``, ``q`` the
``level`` quantile of the absolute ``h``-day log returns of the previous
``CALIBRATION_DAYS`` days that had already ended (split-conformal; the
quantile uses the ``ceil((n + 1) level)``-th smallest, Vovk et al.). Realised
coverage is the share of test days whose ``h``-day outcome fell inside, shown
beside the nominal level.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

import numpy as np

LN4 = 4 * math.log(2)
TEST_DAYS = 250
MIN_TRAIN = 250
REFIT_EVERY = 20
CALIBRATION_DAYS = 250
HORIZONS = (1, 5, 20)
LEVELS = (0.8, 0.95)
TRADING_DAYS = 252


def parkinson(high: np.ndarray, low: np.ndarray) -> np.ndarray:
    return np.log(high / low) ** 2 / LN4


def har_features(rv: np.ndarray) -> np.ndarray:
    """Rows ``t`` (from 21 on): [1, RV_t, mean(RV_t-4..t), mean(RV_t-21..t)]."""
    n = len(rv)
    x = np.full((n, 4), np.nan)
    for t in range(21, n):
        x[t] = (1.0, rv[t], rv[t - 4 : t + 1].mean(), rv[t - 21 : t + 1].mean())
    return x


@dataclass
class VolForecast:
    test_days: int = 0
    har_mse: float | None = None
    rw_mse: float | None = None
    har_qlike: float | None = None
    rw_qlike: float | None = None
    skill_mse: float | None = None
    skill_qlike: float | None = None
    next_day_vol: float | None = None
    """Annualised volatility forecast for the next session (HAR)."""
    coefficients: list[float] | None = None
    reason: str | None = None


def _qlike(actual: np.ndarray, forecast: np.ndarray) -> float:
    ratio = actual / forecast
    return float(np.mean(ratio - np.log(ratio) - 1))


def har_forecast(high: np.ndarray, low: np.ndarray) -> VolForecast:
    """Out-of-sample HAR-RV against the random walk (pure)."""
    out = VolForecast()
    rv = parkinson(high, low)
    rv = np.where(rv > 0, rv, np.nan)
    n = len(rv)
    if n < 22 + MIN_TRAIN + 30 or np.isnan(rv[-TEST_DAYS:]).mean() > 0.2:
        out.reason = f"Needs {22 + MIN_TRAIN + 30} sessions with a high above the low."
        return out
    x = har_features(rv)
    test_start = max(22 + MIN_TRAIN, n - 1 - TEST_DAYS)
    har_f: list[float] = []
    rw_f: list[float] = []
    actual: list[float] = []
    beta: np.ndarray | None = None
    for t in range(test_start, n - 1):
        if beta is None or (t - test_start) % REFIT_EVERY == 0:
            rows = np.arange(21, t)  # targets rv[t'+1] with t'+1 <= t: known on day t
            ok = ~np.isnan(x[rows]).any(axis=1) & ~np.isnan(rv[rows + 1])
            beta, *_ = np.linalg.lstsq(x[rows][ok], rv[rows + 1][ok], rcond=None)
        if np.isnan(x[t]).any() or np.isnan(rv[t + 1]):
            continue
        f = float(x[t] @ beta)
        har_f.append(max(f, 1e-12))
        rw_f.append(float(rv[t]))
        actual.append(float(rv[t + 1]))
    a, h, r = np.array(actual), np.array(har_f), np.array(rw_f)
    out.test_days = len(a)
    out.har_mse, out.rw_mse = float(np.mean((a - h) ** 2)), float(np.mean((a - r) ** 2))
    out.har_qlike, out.rw_qlike = _qlike(a, h), _qlike(a, r)
    out.skill_mse = round(1 - out.har_mse / out.rw_mse, 4) if out.rw_mse else None
    out.skill_qlike = round(1 - out.har_qlike / out.rw_qlike, 4) if out.rw_qlike else None
    rows = np.arange(21, n - 1)
    ok = ~np.isnan(x[rows]).any(axis=1) & ~np.isnan(rv[rows + 1])
    beta, *_ = np.linalg.lstsq(x[rows][ok], rv[rows + 1][ok], rcond=None)
    out.coefficients = [round(float(b), 6) for b in beta]
    if not np.isnan(x[n - 1]).any():
        out.next_day_vol = round(math.sqrt(max(float(x[n - 1] @ beta), 0.0) * TRADING_DAYS), 6)
    return out


def conformal_q(scores: np.ndarray, level: float) -> float | None:
    """The split-conformal quantile: the ceil((n+1) level)-th smallest score."""
    n = len(scores)
    k = math.ceil((n + 1) * level)
    if n == 0 or k > n:
        return None
    return float(np.sort(scores)[k - 1])


@dataclass
class Cone:
    horizon: int
    level: float
    lower: float | None
    upper: float | None
    realised_coverage: float | None
    test_days: int


@dataclass
class PriceCones:
    last_close: float | None
    last_date: date | None
    cones: list[Cone] = field(default_factory=list)
    reason: str | None = None


def price_cones(dates: list[date], close: np.ndarray) -> PriceCones:
    """Conformal cones with realised coverage (pure)."""
    n = len(close)
    out = PriceCones(last_close=float(close[-1]) if n else None, last_date=dates[-1] if n else None)
    logp = np.log(close)
    need = CALIBRATION_DAYS + max(HORIZONS) + 30
    if n < need:
        out.reason = f"Needs {need} sessions of closes."
        return out
    for h in HORIZONS:
        moves = np.abs(logp[h:] - logp[:-h])  # moves[s]: from day s to s + h, known on s + h
        for level in LEVELS:
            hits = 0
            tested = 0
            start = max(CALIBRATION_DAYS + h, n - h - TEST_DAYS)
            for t in range(start, n - h):
                # Calibration: moves that ended on or before day t.
                cal = moves[t - h - CALIBRATION_DAYS + 1 : t - h + 1]
                q = conformal_q(cal, level)
                if q is None:
                    continue
                tested += 1
                hits += int(moves[t] <= q)
            q_now = conformal_q(moves[n - 1 - h - CALIBRATION_DAYS + 1 : n - h], level)
            out.cones.append(Cone(
                horizon=h, level=level,
                lower=None if q_now is None else round(float(close[-1] * math.exp(-q_now)), 4),
                upper=None if q_now is None else round(float(close[-1] * math.exp(q_now)), 4),
                realised_coverage=round(hits / tested, 4) if tested else None,
                test_days=tested,
            ))  # fmt: skip
    return out
