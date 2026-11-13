"""Phase 8.1: time-weighted returns, XIRR, and the #68 headline P&L."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from stockviz._time import utcnow
from stockviz.models import PortfolioSnapshot, Position, PriceBar, Symbol, Trade, TradeSide
from stockviz.models.option import OptionsPosition, OptionStatus, OptionType
from stockviz.services.trading import ensure_default_portfolio
from stockviz.services.trading.returns import period_returns, time_weighted_return, xirr
from tests.test_trading_router import _auth_headers, _make_user

D = Decimal


def test_twr_chains_sub_periods_and_removes_outside_flows() -> None:
    points = [(date(2026, 1, 2), D(100)), (date(2026, 1, 9), D(110)), (date(2026, 1, 16), D(99))]
    # No flows: the chained return is the plain NAV return, gaps and all.
    assert time_weighted_return(points) == pytest.approx(99 / 100 - 1)
    # A deposit of 50 just before the 9 Jan valuation (NAV 160 includes it):
    # (160-50)/100 = 1.10, then 144/160 = 0.90 -> 0.99.
    with_deposit = [points[0], (date(2026, 1, 9), D(160)), (date(2026, 1, 16), D(144))]
    assert time_weighted_return(with_deposit, [(date(2026, 1, 9), D(50))]) == pytest.approx(
        1.10 * 0.90 - 1
    )


def test_xirr_matches_the_published_example() -> None:
    # The worked example in Microsoft's XIRR documentation: 0.373362535.
    flows = [
        (date(2008, 1, 1), D(-10000)),
        (date(2008, 3, 1), D(2750)),
        (date(2008, 10, 30), D(4250)),
        (date(2009, 2, 15), D(3250)),
        (date(2009, 4, 1), D(2750)),
    ]
    result = xirr(flows, as_of=date(2009, 4, 1))
    assert result.rate_pct == pytest.approx(37.3362535, abs=1e-5)
    assert result.flows == 5 and result.reason is None
    # Exactly a year at 10%.
    assert xirr(
        [(date(2025, 1, 1), D(-1000)), (date(2026, 1, 1), D(1100))], as_of=date(2026, 1, 1)
    ).rate_pct == pytest.approx(10.0, abs=1e-6)
    # A total loss solves near -100%, not an error.
    lost = xirr([(date(2025, 1, 1), D(-1000)), (date(2026, 1, 1), D(1))], as_of=date(2026, 1, 1))
    assert lost.rate_pct is not None and lost.rate_pct < -99


def test_xirr_says_why_it_has_no_rate() -> None:
    assert xirr([(date(2026, 1, 1), D(-5))], as_of=date(2026, 6, 1)).reason == (
        "cash flows do not change sign"
    )
    short = xirr([(date(2026, 5, 20), D(-5)), (date(2026, 6, 1), D(6))], as_of=date(2026, 6, 1))
    assert short.rate_pct is None and short.reason == "held under 30 days"


def test_periods_start_at_the_last_point_before_them() -> None:
    opened = date(2025, 11, 3)
    points = [
        (opened, D(100000)),
        (date(2025, 12, 31), D(104000)),
        (date(2026, 10, 30), D(110000)),
        (date(2026, 11, 13), D(112200)),
    ]
    by = {r.period: r for r in period_returns(points, as_of=date(2026, 11, 13), opened=opened)}
    assert by["YTD"].start_date == date(2025, 12, 31)
    assert by["YTD"].return_pct == pytest.approx((112200 / 104000 - 1) * 100)
    # 13 Oct has no snapshot: the period starts at the last point before it.
    assert by["1M"].start_date == date(2025, 12, 31)
    assert by["ALL"].return_pct == pytest.approx(12.2)
    assert by["ALL"].annualised_pct == pytest.approx(((1.122 ** (365 / 375)) - 1) * 100)
    # A year back is 13 Nov 2025: the last point before it is the opening.
    assert by["1Y"].start_date == opened and by["1Y"].return_pct == pytest.approx(12.2)
    assert by["3M"].annualised_pct is None  # under a year: not annualised
    young = {
        r.period: r
        for r in period_returns(points[2:], as_of=date(2026, 11, 13), opened=date(2026, 10, 30))
    }
    assert young["1Y"].return_pct is None
    assert young["1Y"].reason == "account is younger than the period"
    assert young["ALL"].return_pct == pytest.approx(2.0)


def _bar(ticker: str, day: datetime, close: str) -> PriceBar:
    c = D(close)
    return PriceBar(
        ticker=ticker, ts=day, interval="1d", open=c, high=c, low=c, close=c,
        volume=1000, source="test",
    )  # fmt: skip


def test_headline_pl_includes_options_and_realized_gains(
    session: Session, client: TestClient
) -> None:
    """#68's reproduction: sell a winner, hold a loser, hold a call."""
    session.add_all([Symbol(ticker="AAPL", name="Apple"), Symbol(ticker="MSFT", name="Msft")])
    session.commit()
    now = utcnow()
    session.add_all(
        [_bar("AAPL", now - timedelta(days=1), "150"), _bar("MSFT", now - timedelta(days=1), "90")]
    )
    user_id = _make_user(session)
    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.id is not None
    bought = now - timedelta(days=200)
    session.add_all(
        [
            Trade(portfolio_id=portfolio.id, ticker="AAPL", side=TradeSide.BUY,
                  quantity=D(10), price=D(100), fx_rate=D(1), ts=bought),
            Trade(portfolio_id=portfolio.id, ticker="AAPL", side=TradeSide.SELL,
                  quantity=D(10), price=D(150), fx_rate=D(1), realized_pnl=D(500),
                  ts=now - timedelta(days=10)),
            Trade(portfolio_id=portfolio.id, ticker="MSFT", side=TradeSide.BUY,
                  quantity=D(10), price=D(100), fx_rate=D(1), ts=bought),
            Position(portfolio_id=portfolio.id, ticker="MSFT", quantity=D(10), avg_cost=D(100)),
            OptionsPosition(user_id=user_id, portfolio_id=portfolio.id, ticker="AAPL",
                            option_type=OptionType.CALL, strike=D(140), expiry=date(2000, 1, 1),
                            quantity=1, premium_paid=D(100), status=OptionStatus.EXPIRED,
                            proceeds=D(0), realized_pnl=D(-100), settled_at=now - timedelta(days=5),
                            opened_at=now - timedelta(days=60)),
        ]
    )  # fmt: skip
    session.commit()

    body = client.get("/v1/portfolio/overview", headers=_auth_headers(user_id)).json()
    p = body["portfolio"]
    assert D(p["realized_pl"]) == D(400)  # 500 on AAPL, -100 on the expired call
    assert p["realized_pl_unavailable"] == 0
    assert D(p["unrealized_pl_equity"]) == D(-100)  # MSFT 10 x (90 - 100)
    assert D(p["unrealized_pl"]) == D(p["unrealized_pl_equity"]) + D(p["unrealized_pl_options"])

    returns = body["analytics"]["returns"]
    assert returns["twr_method"] == "time_weighted"
    assert returns["xirr_method"] == "money_weighted_xirr"
    assert [r["period"] for r in returns["periods"]] == ["1M", "3M", "YTD", "1Y", "ALL"]
    holdings = {h["ticker"]: h for h in returns["holdings"]}
    # MSFT: -1000 two hundred days ago, +900 today.
    expected = ((900 / 1000) ** (365 / 200) - 1) * 100
    assert holdings["MSFT"]["xirr"]["rate_pct"] == pytest.approx(expected, abs=1e-4)
    # The only contract expired worthless: its premium is all lost.
    assert holdings["OPTIONS"]["xirr"]["rate_pct"] == -100.0


def test_snapshot_series_feeds_the_periods(session: Session, client: TestClient) -> None:
    user_id = _make_user(session)
    portfolio = ensure_default_portfolio(session, user_id)
    today = utcnow().date()
    session.add_all(
        [
            PortfolioSnapshot(user_id=user_id, date=today - timedelta(days=2), nav=D(100000)),
            PortfolioSnapshot(user_id=user_id, date=today - timedelta(days=1), nav=D(100000)),
        ]
    )
    session.commit()
    assert portfolio.opening_nav is not None
    returns = client.get("/v1/portfolio/analytics", headers=_auth_headers(user_id)).json()[
        "returns"
    ]
    all_time = next(r for r in returns["periods"] if r["period"] == "ALL")
    assert all_time["return_pct"] == pytest.approx(0.0)
    assert returns["account_xirr"]["reason"] == "cash flows do not change sign" or (
        returns["account_xirr"]["reason"] == "held under 30 days"
    )
