"""Phase 8.4: stress tests applied instantly to today's book.

The combined shock is worked by hand in
docs/benchmarks/2026-11-13-risk-hand-check.md.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from stockviz._time import utcnow
from stockviz.models import Position, Symbol
from stockviz.models.market import FxRate
from stockviz.services.risk.stress import beta
from stockviz.services.trading import ensure_default_portfolio
from stockviz.services.trading.cash import credit
from tests.test_returns import _bar
from tests.test_risk import _weekdays
from tests.test_trading_router import _auth_headers, _make_user

D = Decimal


def _scenarios(client: TestClient, user_id: int) -> dict[str, dict]:
    body = client.get("/v1/portfolio/stress", headers=_auth_headers(user_id)).json()
    assert body["method"] == "instant_revaluation"
    return {s["key"]: s for s in body["scenarios"]}


def test_combined_shock_matches_the_hand_check(session: Session, client: TestClient) -> None:
    session.add_all([Symbol(ticker="AAPL", name="Apple"),
                     Symbol(ticker="RELIANCE.NS", name="Reliance", currency="INR")])  # fmt: skip
    session.commit()
    yesterday = utcnow() - timedelta(days=1)
    session.add_all([_bar("AAPL", yesterday, "100"), _bar("RELIANCE.NS", yesterday, "2500"),
                     FxRate(currency="INR", date=yesterday.date(), usd_rate=D("0.012"))])  # fmt: skip
    user_id = _make_user(session)
    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.id is not None
    # AAPL 100 x 100 = 10,000 USD; RELIANCE 166 x 2,500 x 0.012 = 4,980 USD.
    session.add_all([Position(portfolio_id=portfolio.id, ticker="AAPL", quantity=D(100), avg_cost=D(90)),
                     Position(portfolio_id=portfolio.id, ticker="RELIANCE.NS", quantity=D(166), avg_cost=D(2400))])  # fmt: skip
    credit(session, portfolio, "INR", D(100000))  # 1,200 USD of rupees
    session.commit()

    s = _scenarios(client, user_id)["combined"]
    # AAPL -20%: -2,000. RELIANCE (0.8 x 0.9 - 1 = -28%): -1,394.40.
    # Rupee cash -10%: -120. Total -3,514.40.
    assert s["change"] == pytest.approx(-3514.40, abs=0.01)
    assert [d["ticker"] for d in s["drivers"]] == ["AAPL", "RELIANCE.NS", "INR cash"]
    assert s["nav_after"] == pytest.approx(s["nav_before"] - 3514.40, abs=0.01)
    us = _scenarios(client, user_id)["us_minus_10"]
    assert us["change"] == pytest.approx(-1000.0, abs=0.01)


def test_historical_window_uses_own_history_or_a_beta_proxy(
    session: Session, client: TestClient
) -> None:
    session.add_all([Symbol(ticker="AAPL", name="Apple"), Symbol(ticker="MSFT", name="Msft"),
                     Symbol(ticker="NEW", name="No index"), Symbol(ticker="^GSPC", name="S&P 500")])  # fmt: skip
    session.commit()
    # COVID window: AAPL 100 -> 70 (-30%); the index 3,000 -> 2,400 (-20%).
    for ticker, start, end in (("AAPL", "100", "70"), ("^GSPC", "3000", "2400")):
        session.add_all([_bar(ticker, datetime(2020, 2, 19), start),
                         _bar(ticker, datetime(2020, 3, 23), end)])  # fmt: skip
    # Recent history: MSFT moves exactly twice the index each day -> beta 2.
    index, msft = 3000.0, 100.0
    for i, day in enumerate(_weekdays(120)):
        r = 0.01 if i % 2 else -0.008
        index *= 1 + r
        msft *= 1 + 2 * r
        session.add_all([_bar("^GSPC", day, f"{index:.6f}"), _bar("MSFT", day, f"{msft:.6f}")])
        session.add(_bar("AAPL", day, "100"))
        session.add(_bar("NEW", day, "50"))
    user_id = _make_user(session)
    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.id is not None
    session.add_all([Position(portfolio_id=portfolio.id, ticker="AAPL", quantity=D(10), avg_cost=D(1)),
                     Position(portfolio_id=portfolio.id, ticker="MSFT", quantity=D(10), avg_cost=D(1))])  # fmt: skip
    session.commit()

    covid = _scenarios(client, user_id)["covid_2020"]
    assert covid["kind"] == "historical" and covid["start"] == "2020-02-19"
    msft_value = 10 * float(f"{msft:.6f}")
    expected = 1000 * -0.30 + msft_value * (-0.20 * 2)
    assert covid["change"] == pytest.approx(expected, rel=1e-3)
    assert covid["proxied"] == ["MSFT"]
    gfc = _scenarios(client, user_id)["gfc_2008"]
    assert sorted(gfc["missing"]) == ["AAPL", "MSFT"] and gfc["change"] == 0


def test_beta_needs_enough_shared_days() -> None:
    from datetime import date

    days = [date(2026, 1, 1) + timedelta(days=i) for i in range(80)]
    index = {d: (0.01 if i % 2 else -0.01) for i, d in enumerate(days)}
    assert beta({d: 1.5 * r for d, r in index.items()}, index) == pytest.approx(1.5)
    assert beta({d: index[d] for d in days[:30]}, index) is None
