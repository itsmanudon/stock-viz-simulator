"""Phase 8.5: pre-trade limits, off until the user sets them."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from stockviz._time import utcnow
from stockviz.models import Symbol, Trade
from stockviz.models.order import OrderStatus, OrderType, PendingOrder
from stockviz.models.portfolio import Portfolio, TradeSide
from stockviz.services.trading import ensure_default_portfolio
from stockviz.services.trading.orders import settle_pending_orders
from tests.test_returns import _bar
from tests.test_trading_router import _auth_headers, _make_user

D = Decimal


def _account(session: Session) -> tuple[int, dict[str, str]]:
    session.add_all([Symbol(ticker="AAPL", name="Apple", sector="Technology"),
                     Symbol(ticker="KO", name="Coca-Cola", sector="Staples")])  # fmt: skip
    session.commit()
    yesterday = utcnow() - timedelta(days=1)
    session.add_all([_bar("AAPL", yesterday, "100"), _bar("KO", yesterday, "50")])
    session.commit()
    user_id = _make_user(session)
    ensure_default_portfolio(session, user_id)  # $100,000 cash
    return user_id, _auth_headers(user_id)


def test_no_limits_by_default(session: Session, client: TestClient) -> None:
    _, headers = _account(session)
    body = client.get("/v1/portfolio/limits", headers=headers).json()
    assert all(body[k] is None for k in ("max_position_pct", "max_order_pct", "max_var_pct"))
    big = client.post(
        "/v1/trades", headers=headers, json={"ticker": "AAPL", "side": "buy", "quantity": "900"}
    )
    assert big.status_code == 201  # 90% of the account in one order, allowed


def test_a_buy_over_a_limit_is_refused_and_nothing_moves(
    session: Session, client: TestClient
) -> None:
    user_id, headers = _account(session)
    put = client.put("/v1/portfolio/limits", headers=headers, json={"max_position_pct": "10"})
    assert put.status_code == 200 and put.json()["max_position_pct"] == "10.00"

    refused = client.post(
        "/v1/trades", headers=headers, json={"ticker": "AAPL", "side": "buy", "quantity": "150"}
    )
    assert refused.status_code == 409
    assert (
        "position to 15.00% of the account, over your limit of 10.00%" in refused.json()["detail"]
    )
    portfolio = session.exec(select(Portfolio).where(Portfolio.user_id == user_id)).one()
    session.refresh(portfolio)
    assert portfolio.cash_balance == D("100000")
    assert session.exec(select(Trade)).all() == []

    ok = client.post(
        "/v1/trades", headers=headers, json={"ticker": "AAPL", "side": "buy", "quantity": "90"}
    )
    assert ok.status_code == 201  # 9%


def test_sells_are_never_checked(session: Session, client: TestClient) -> None:
    _, headers = _account(session)
    assert (
        client.post(
            "/v1/trades", headers=headers, json={"ticker": "AAPL", "side": "buy", "quantity": "300"}
        ).status_code
        == 201
    )
    # A limit set after the fact: the holding is now over it, and selling is still allowed.
    client.put("/v1/portfolio/limits", headers=headers, json={"max_position_pct": "5"})
    sell = client.post(
        "/v1/trades", headers=headers, json={"ticker": "AAPL", "side": "sell", "quantity": "100"}
    )
    assert sell.status_code == 201


def test_preview_shows_each_limit_after_the_fill(session: Session, client: TestClient) -> None:
    _, headers = _account(session)
    client.post(
        "/v1/trades", headers=headers, json={"ticker": "AAPL", "side": "buy", "quantity": "100"}
    )
    client.put(
        "/v1/portfolio/limits",
        headers=headers,
        json={"max_order_pct": "5", "max_sector_pct": "15", "max_currency_pct": "50"},
    )
    body = client.get("/v1/portfolio/limits/check?ticker=AAPL&quantity=80", headers=headers).json()
    checks = {c["limit"]: c for c in body["checks"]}
    assert checks["max_order_pct"]["value_after"] == 8.0 and checks["max_order_pct"]["breached"]
    # Technology: 10,000 held + 8,000 = 18% of 100,000.
    assert checks["max_sector_pct"]["value_after"] == 18.0
    assert checks["max_currency_pct"]["value_after"] is None  # USD is the base
    assert body["breached"] is True
    other = client.get("/v1/portfolio/limits/check?ticker=KO&quantity=10", headers=headers).json()
    assert other["breached"] is False


def test_settlement_cancels_an_order_that_would_breach(
    session: Session, client: TestClient
) -> None:
    user_id, headers = _account(session)
    client.put("/v1/portfolio/limits", headers=headers, json={"max_order_pct": "5"})
    portfolio = session.exec(select(Portfolio).where(Portfolio.user_id == user_id)).one()
    assert portfolio.id is not None
    order = PendingOrder(
        portfolio_id=portfolio.id, ticker="AAPL", side=TradeSide.BUY,
        order_type=OrderType.LIMIT, quantity=D(100), limit_price=D(150),
    )  # fmt: skip
    session.add(order)
    session.commit()
    settle_pending_orders(session)
    session.refresh(order)
    assert order.status == OrderStatus.CANCELLED
    assert "single order to 10.00%" in (order.cancel_reason or "")


def test_limits_must_be_percentages(session: Session, client: TestClient) -> None:
    _, headers = _account(session)
    for bad in ("0", "-5", "100.5"):
        r = client.put("/v1/portfolio/limits", headers=headers, json={"max_order_pct": bad})
        assert r.status_code == 422


def test_var_limit_says_when_it_cannot_be_checked(session: Session, client: TestClient) -> None:
    _, headers = _account(session)
    client.put("/v1/portfolio/limits", headers=headers, json={"max_var_pct": "1"})
    body = client.get("/v1/portfolio/limits/check?ticker=AAPL&quantity=10", headers=headers).json()
    (check,) = body["checks"]
    assert check["value_after"] is None and check["breached"] is False
    assert check["note"].startswith("not checked: ")
    # One bar of history is not enough, so the buy goes through.
    assert (
        client.post(
            "/v1/trades", headers=headers, json={"ticker": "AAPL", "side": "buy", "quantity": "10"}
        ).status_code
        == 201
    )


def test_an_option_premium_over_the_order_limit_is_refused(
    session: Session, client: TestClient
) -> None:
    _, headers = _account(session)
    client.put("/v1/portfolio/limits", headers=headers, json={"max_order_pct": "0.01"})
    expiry = (date.today() + timedelta(days=30)).isoformat()
    r = client.post(
        "/v1/options/trade",
        headers=headers,
        json={"action": "open", "ticker": "AAPL", "option_type": "call", "strike": "100",
              "expiry": expiry, "quantity": 1},
    )  # fmt: skip
    assert r.status_code == 409, r.text
    assert "single-order limit of 0.01%" in r.json()["detail"]
