"""Portfolio optimisation on stored closes (A7.11, M10.6), with PyPortfolioOpt.

The owner chose PyPortfolioOpt (MIT) on 27 Nov 2026. Inputs are the symbols'
daily closes on their common sessions over the last ``years``; every method
is in-sample on that window and says so.

- **Covariance:** Ledoit-Wolf shrinkage (``CovarianceShrinkage.ledoit_wolf``).
- **Expected returns:** mean historical daily return x 252 (``mean_historical_return``,
  compounded). Noisy by nature; max Sharpe leans on them, HRP and min
  volatility do not.
- ``hrp``: hierarchical risk parity (single linkage on correlation distance,
  recursive bisection; López de Prado 2016). No expected returns.
- ``min_volatility`` and ``max_sharpe``: the efficient frontier, long only,
  weights capped at ``max_weight``.
- ``min_cvar``: minimum CVaR at ``beta`` over the window's daily returns used
  as scenarios (Rockafellar and Uryasev 2000).
- ``black_litterman``: the market-implied prior from stored USD market caps
  (risk aversion ``delta``, default 2.5, stated), the caller's absolute views
  with Idzorek confidences, then max Sharpe on the posterior.

Whole shares come from ``DiscreteAllocation.greedy_portfolio`` at the latest
common close. Nothing here places an order.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd
from sqlmodel import Session, col, select

from stockviz.models import PriceBar, Symbol, SymbolMetrics

METHODS = ("hrp", "min_volatility", "max_sharpe", "min_cvar", "black_litterman")
MIN_SESSIONS = 252
TRADING_DAYS = 252


class OptimiseError(ValueError):
    """The inputs cannot be optimised; ``str()`` says why (an HTTP 400)."""


@dataclass(frozen=True)
class View:
    ticker: str
    expected_return: float
    confidence: float


@dataclass
class Result:
    method: str
    tickers: list[str]
    currency: str
    first: date
    last: date
    sessions: int
    weights: dict[str, float]
    expected_return: float | None
    volatility: float | None
    sharpe: float | None
    cvar: float | None
    equal_weight: dict[str, float | None]
    allocation: dict[str, int] = field(default_factory=dict)
    leftover: float | None = None
    prices: dict[str, float] = field(default_factory=dict)
    prior: dict[str, float] | None = None
    posterior: dict[str, float] | None = None
    notes: list[str] = field(default_factory=list)


def _as_map(values: object, tickers: list[str]) -> dict[str, float]:
    """A pandas Series or array keyed like ``tickers`` as plain floats."""
    arr = np.asarray(values, dtype=float).reshape(-1)
    return {t: float(v) for t, v in zip(tickers, arr, strict=True)}


def load_closes(session: Session, tickers: list[str], years: int) -> tuple[pd.DataFrame, str]:
    """Closes on the tickers' common sessions over the last ``years`` (columns in order)."""
    symbols = {
        s.ticker: s for s in session.exec(select(Symbol).where(col(Symbol.ticker).in_(tickers)))
    }
    missing = [t for t in tickers if t not in symbols]
    if missing:
        raise LookupError(", ".join(missing))
    currencies = {symbols[t].currency for t in tickers}
    if len(currencies) > 1:
        raise OptimiseError(
            f"symbols trade in different currencies ({', '.join(sorted(currencies))})"
        )
    rows = session.exec(
        select(col(PriceBar.ticker), col(PriceBar.ts), col(PriceBar.close)).where(
            col(PriceBar.ticker).in_(tickers), col(PriceBar.interval) == "1d"
        )
    ).all()
    if not rows:
        raise OptimiseError("no stored daily closes for these symbols")
    frame = pd.DataFrame(rows, columns=["ticker", "ts", "close"])
    frame["day"] = pd.to_datetime(frame["ts"]).dt.normalize()
    wide = frame.pivot_table(index="day", columns="ticker", values="close", aggfunc="last")
    wide = wide.reindex(columns=tickers).astype(float).dropna()
    if wide.empty:
        raise OptimiseError("the symbols share no stored sessions")
    start = wide.index[-1] - timedelta(days=int(365.25 * years))
    wide = wide[wide.index > start]
    if len(wide) < MIN_SESSIONS:
        raise OptimiseError(f"needs {MIN_SESSIONS} common sessions; {len(wide)} in the window")
    return pd.DataFrame(wide), currencies.pop()


def _perf(
    weights: dict[str, float], mu: pd.Series, cov: pd.DataFrame, rf: float
) -> dict[str, float | None]:
    w = np.array([weights.get(str(t), 0.0) for t in mu.index])
    ret = float(w @ mu.to_numpy())
    vol = float(np.sqrt(w @ cov.to_numpy() @ w))
    return {
        "expected_return": ret,
        "volatility": vol,
        "sharpe": (ret - rf) / vol if vol > 0 else None,
    }


def _cvar(weights: dict[str, float], returns: pd.DataFrame, beta: float) -> float:
    port = returns.to_numpy() @ np.array([weights.get(str(t), 0.0) for t in returns.columns])
    cut = np.quantile(port, 1 - beta)
    tail = port[port <= cut]
    return float(-tail.mean()) if tail.size else 0.0


def optimise(
    closes: pd.DataFrame,
    currency: str,
    method: str,
    *,
    risk_free_rate: float = 0.04,
    max_weight: float = 1.0,
    beta: float = 0.95,
    cash: float | None = None,
    market_caps: dict[str, float] | None = None,
    views: list[View] | None = None,
    delta: float = 2.5,
) -> Result:
    from pypfopt import (
        EfficientCVaR,
        EfficientFrontier,
        HRPOpt,
        black_litterman,
        expected_returns,
        risk_models,
    )
    from pypfopt.black_litterman import BlackLittermanModel
    from pypfopt.discrete_allocation import DiscreteAllocation

    if method not in METHODS:
        raise OptimiseError(f"method must be one of {', '.join(METHODS)}")
    tickers = [str(c) for c in closes.columns]
    n = len(tickers)
    if max_weight * n < 1 - 1e-9:
        raise OptimiseError(f"max_weight {max_weight:.2f} x {n} symbols cannot reach 100%")
    returns = closes.pct_change().dropna()
    mu = expected_returns.mean_historical_return(closes, frequency=TRADING_DAYS)
    cov = risk_models.CovarianceShrinkage(closes, frequency=TRADING_DAYS).ledoit_wolf()
    bounds = (0.0, max_weight)
    notes = [
        f"In-sample on {len(closes)} common sessions; not a forecast and not advice.",
        "Covariance: Ledoit-Wolf shrinkage of daily returns, annualised x252.",
    ]
    prior = posterior = None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            if method == "hrp":
                hrp = HRPOpt(cov_matrix=cov)
                raw = hrp.optimize(linkage_method="single")
                notes.append(
                    "HRP: single linkage on correlation distance; ignores expected returns."
                )
            elif method in ("min_volatility", "max_sharpe"):
                ef = EfficientFrontier(mu, cov, weight_bounds=bounds)
                raw = (
                    ef.min_volatility()
                    if method == "min_volatility"
                    else ef.max_sharpe(risk_free_rate=risk_free_rate)
                )
                if method == "max_sharpe":
                    notes.append(
                        "Max Sharpe uses mean historical returns, which are noisy: small changes "
                        "in the window can move weights a lot."
                    )
            elif method == "min_cvar":
                ecv = EfficientCVaR(mu, returns, beta=beta, weight_bounds=bounds)
                raw = ecv.min_cvar()
                notes.append(
                    f"Min CVaR at {beta:.0%}: the window's daily returns are the scenarios."
                )
            else:
                caps = {t: (market_caps or {}).get(t) for t in tickers}
                absent = [t for t, c in caps.items() if not c]
                if absent:
                    raise OptimiseError(f"no stored market cap for {', '.join(absent)}")
                pi = black_litterman.market_implied_prior_returns(
                    pd.Series(caps, dtype=float), delta, cov, risk_free_rate=risk_free_rate
                )
                prior = _as_map(pi, tickers)
                vs = [v for v in (views or []) if v.ticker in tickers]
                if vs:
                    bl = BlackLittermanModel(
                        cov,
                        pi=pi,
                        absolute_views={v.ticker: v.expected_return for v in vs},
                        omega="idzorek",
                        view_confidences=[v.confidence for v in vs],
                    )
                    post_mu, post_cov = bl.bl_returns(), bl.bl_cov()
                else:
                    post_mu, post_cov = pi, cov
                posterior = _as_map(post_mu, tickers)
                ef = EfficientFrontier(post_mu, post_cov, weight_bounds=bounds)
                raw = ef.max_sharpe(risk_free_rate=risk_free_rate)
                notes.append(
                    f"Black-Litterman: prior implied by USD market caps at risk aversion {delta}; "
                    f"{len(vs)} view(s), Idzorek confidences; max Sharpe on the posterior."
                )
        except OptimiseError:
            raise
        except Exception as exc:  # solver failures are inputs the method cannot use
            raise OptimiseError(
                f"the optimiser could not solve this ({exc.__class__.__name__})"
            ) from exc
    raw_items: dict[object, object] = dict(raw)
    raw_map = {str(k): float(str(v)) for k, v in raw_items.items()}
    weights = {t: round(raw_map.get(t, 0.0), 6) for t in tickers}
    weights = {t: (w if w > 1e-6 else 0.0) for t, w in weights.items()}
    total = sum(weights.values()) or 1.0
    weights = {t: w / total for t, w in weights.items()}
    perf = _perf(weights, mu, cov, risk_free_rate)
    equal = dict.fromkeys(tickers, 1 / n)
    eq_perf = _perf(equal, mu, cov, risk_free_rate)
    result = Result(
        method=method,
        tickers=tickers,
        currency=currency,
        first=date.fromisoformat(str(closes.index[0])[:10]),
        last=date.fromisoformat(str(closes.index[-1])[:10]),
        sessions=len(closes),
        weights=weights,
        expected_return=perf["expected_return"],
        volatility=perf["volatility"],
        sharpe=perf["sharpe"],
        cvar=_cvar(weights, returns, beta),
        equal_weight={**eq_perf, "cvar": _cvar(equal, returns, beta)},
        prior=prior,
        posterior=posterior,
        notes=notes,
    )
    if cash:
        latest = closes.iloc[-1]
        result.prices = {t: float(latest[t]) for t in tickers}
        held = {t: w for t, w in weights.items() if w > 0}
        alloc, leftover = DiscreteAllocation(
            held,
            latest[list(held)],
            total_portfolio_value=cash,  # pyright: ignore[reportArgumentType]
        ).greedy_portfolio()
        result.allocation = {t: int(alloc.get(t, 0)) for t in tickers}
        result.leftover = float(leftover)
        notes.append(
            "Whole shares by greedy allocation at the latest common close; no order is placed."
        )
    return result


def market_caps(session: Session, tickers: list[str]) -> dict[str, float]:
    rows = session.exec(
        select(SymbolMetrics.ticker, SymbolMetrics.market_cap_usd).where(
            col(SymbolMetrics.ticker).in_(tickers)
        )
    ).all()
    return {t: float(c) for t, c in rows if c}
