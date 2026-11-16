"""Phase 8.3: historical VaR and CVaR, the block bootstrap, the risk endpoint.

The 20-scenario case is worked by hand in
docs/benchmarks/2026-11-13-risk-hand-check.md.
"""

from __future__ import annotations

import math
from datetime import timedelta
from decimal import Decimal

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from stockviz._time import utcnow
from stockviz.models import Position, Symbol
from stockviz.models.market import FxRate
from stockviz.services.risk.engine import (
    block_bootstrap,
    compound_windows,
    historical_var,
    tail_count,
)
from stockviz.services.trading import ensure_default_portfolio
from tests.test_returns import _bar
from tests.test_trading_router import _auth_headers, _make_user

D = Decimal

# The hand-check sample: twenty days of P&L in dollars.
HAND_PNL = [120, -340, 55, -80, 410, -15, -260, 90, 30, -500,
            75, -45, 160, -120, 20, 300, -210, 5, -60, 140]  # fmt: skip


def test_hand_checked_var_and_cvar() -> None:
    # 90%: k = ceil(20 x 0.10) = 2 -> the two worst losses are 500 and 340.
    result = historical_var(HAND_PNL, confidence=0.90, horizon_days=1)
    assert result is not None
    assert (result.tail_count, result.var, result.cvar) == (2, 340, 420)
    # 95%: k = ceil(20 x 0.05) = 1 -> VaR = CVaR = 500.
    result = historical_var(HAND_PNL, confidence=0.95, horizon_days=1)
    assert result is not None and (result.var, result.cvar) == (500, 500)
    # 75%: k = 5 -> 500, 340, 260, 210, 120; mean 286.
    result = historical_var(HAND_PNL, confidence=0.75, horizon_days=1)
    assert result is not None and (result.var, result.cvar) == (120, 286)
    assert tail_count(500, 0.95) == 25 and tail_count(500, 0.99) == 5


def test_ten_day_windows_compound_real_runs() -> None:
    daily = np.array([[0.10], [-0.10], [0.20]])
    two = compound_windows(daily, 2)[:, 0]
    assert two == pytest.approx([1.1 * 0.9 - 1, 0.9 * 1.2 - 1])
    assert compound_windows(daily, 1) is daily


def test_bootstrap_is_repeatable_and_exact_for_a_constant_series() -> None:
    flat = np.full(300, 0.001)
    result = block_bootstrap(flat, start_value=100_000, paths=500)
    assert result.percentiles[5] == pytest.approx(100_000 * 1.001**252)
    assert result.percentiles[95] == pytest.approx(result.percentiles[5])
    noisy = np.random.default_rng(1).normal(0, 0.02, 300)
    first = block_bootstrap(noisy, start_value=1.0, paths=2000)
    assert first == block_bootstrap(noisy, start_value=1.0, paths=2000)
    assert first.percentiles[5] < first.percentiles[50] < first.percentiles[95]


def _weekdays(n: int) -> list:
    days, day = [], utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    while len(days) < n:
        day -= timedelta(days=1)
        if day.weekday() < 5:
            days.append(day)
    return list(reversed(days))


def _path(start: float, seed: int, n: int) -> list[float]:
    rng = np.random.default_rng(seed)
    closes = [start]
    for r in rng.normal(0.0004, 0.015, n - 1):
        closes.append(round(closes[-1] * (1 + r), 2))
    return closes


def test_risk_endpoint_matches_an_independent_calculation(
    session: Session, client: TestClient
) -> None:
    days = _weekdays(300)
    aapl, rel = _path(150, 7, 300), _path(2500, 8, 300)
    inr = [round(0.0120 * (1 + 0.002 * math.sin(i / 9)), 6) for i in range(300)]
    session.add_all([Symbol(ticker="AAPL", name="Apple"),
                     Symbol(ticker="RELIANCE.NS", name="Reliance", currency="INR")])  # fmt: skip
    session.commit()
    for day, a, r, fx in zip(days, aapl, rel, inr, strict=True):
        session.add_all([_bar("AAPL", day, str(a)), _bar("RELIANCE.NS", day, str(r)),
                         FxRate(currency="INR", date=day.date(), usd_rate=D(str(fx)))])  # fmt: skip
    user_id = _make_user(session)
    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.id is not None
    session.add_all([Position(portfolio_id=portfolio.id, ticker="AAPL", quantity=D(100), avg_cost=D(140)),
                     Position(portfolio_id=portfolio.id, ticker="RELIANCE.NS", quantity=D(20), avg_cost=D(2400))])  # fmt: skip
    session.commit()

    body = client.get("/v1/portfolio/risk", headers=_auth_headers(user_id)).json()
    assert body["reason"] is None, body
    assert body["method"] == "historical_simulation" and body["currency"] == "USD"
    assert body["holdings_included"] == 2 and body["proxied"] == []

    # Independent: the first return date has no prior FX rate in the window,
    # so scenarios start on the third bar (298 of them).
    value_a = 100 * aapl[-1]
    value_r = 20 * rel[-1] * inr[-1]
    pnl = []
    for i in range(2, 300):
        ra = aapl[i] / aapl[i - 1] - 1
        rr = (1 + rel[i] / rel[i - 1] - 1) * (1 + inr[i] / inr[i - 1] - 1) - 1
        pnl.append(value_a * ra + value_r * rr)
    assert body["window"]["sessions"] == len(pnl) == 298
    losses = sorted((-x for x in pnl), reverse=True)
    one_day = {(v["confidence"], v["horizon_days"]): v for v in body["var"]}
    k95 = math.ceil(298 * 0.05)  # 15
    assert one_day[(0.95, 1)]["tail_count"] == k95
    assert one_day[(0.95, 1)]["var"] == pytest.approx(losses[k95 - 1], abs=0.01)
    assert one_day[(0.95, 1)]["cvar"] == pytest.approx(sum(losses[:k95]) / k95, abs=0.01)
    assert one_day[(0.99, 10)]["scenarios"] == 298 - 9
    assert one_day[(0.99, 1)]["cvar"] >= one_day[(0.99, 1)]["var"]
    mc = body["monte_carlo"]
    assert mc["method"] == "stationary_block_bootstrap" and mc["paths"] == 10_000
    assert mc["percentiles"]["5"] < mc["percentiles"]["50"] < mc["percentiles"]["95"]


def test_short_history_says_so(session: Session, client: TestClient) -> None:
    session.add(Symbol(ticker="AAPL", name="Apple"))
    session.commit()
    for day, close in zip(_weekdays(40), _path(150, 3, 40), strict=True):
        session.add(_bar("AAPL", day, str(close)))
    user_id = _make_user(session)
    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.id is not None
    session.add(Position(portfolio_id=portfolio.id, ticker="AAPL", quantity=D(1), avg_cost=D(1)))
    session.commit()
    body = client.get("/v1/portfolio/risk", headers=_auth_headers(user_id)).json()
    assert body["var"] == [] and body["monte_carlo"] is None
    assert body["reason"] == "38 sessions of history; 250 are needed"


def test_a_long_option_cannot_lose_more_than_its_value(
    session: Session, client: TestClient
) -> None:
    from datetime import date

    from stockviz.models.option import OptionsPosition, OptionType

    session.add(Symbol(ticker="AAPL", name="Apple"))
    session.commit()
    closes = _path(150, 11, 300)
    for day, close in zip(_weekdays(300), closes, strict=True):
        session.add(_bar("AAPL", day, str(close)))
    user_id = _make_user(session)
    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.id is not None
    today = utcnow().date()
    session.add(
        OptionsPosition(
            user_id=user_id, portfolio_id=portfolio.id, ticker="AAPL",
            option_type=OptionType.CALL, strike=D(str(round(closes[-1] * 1.05))),
            expiry=date.fromordinal(today.toordinal() + 20), quantity=2, premium_paid=D(500),
        )
    )  # fmt: skip
    session.commit()
    overview = client.get("/v1/portfolio", headers=_auth_headers(user_id)).json()
    value = float(overview["options_market_value"])
    body = client.get("/v1/portfolio/risk", headers=_auth_headers(user_id)).json()
    assert body["holdings_included"] == 1 and body["reason"] is None
    for figure in body["var"]:
        assert 0 < figure["cvar"] <= value + 0.01


def test_goal_probability_is_the_share_of_paths_reaching_it() -> None:
    flat = np.full(300, 0.001)
    end = 100_000 * 1.001**252
    reached = block_bootstrap(flat, start_value=100_000, paths=200, goal=end - 1)
    missed = block_bootstrap(flat, start_value=100_000, paths=200, goal=end + 1)
    assert (reached.prob_goal, missed.prob_goal) == (1.0, 0.0)
    noisy = np.random.default_rng(2).normal(0.0005, 0.02, 300)
    median = block_bootstrap(noisy, start_value=1.0, paths=4000).percentiles[50]
    half = block_bootstrap(noisy, start_value=1.0, paths=4000, goal=median)
    assert half.prob_goal == pytest.approx(0.5, abs=0.01)
