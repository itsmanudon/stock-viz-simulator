"""Phase 8.2: exposure by sector, country and currency; FX attribution."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from stockviz._time import utcnow
from stockviz.models import Position, Symbol, Trade, TradeSide
from stockviz.models.market import FxRate
from stockviz.services.trading import ensure_default_portfolio
from tests.test_returns import _bar
from tests.test_trading_router import _auth_headers, _make_user

D = Decimal


def _book(session: Session) -> int:
    session.add_all(
        [
            Symbol(ticker="AAPL", name="Apple", sector="Technology"),
            Symbol(ticker="SAP.DE", name="SAP", sector="Technology", currency="EUR"),
        ]
    )
    session.commit()
    now = utcnow()
    session.add_all(
        [
            _bar("AAPL", now - timedelta(days=1), "150"),
            _bar("SAP.DE", now - timedelta(days=1), "120"),
            FxRate(currency="EUR", date=(now - timedelta(days=1)).date(), usd_rate=D("1.05")),
        ]
    )
    user_id = _make_user(session)
    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.id is not None
    pid = portfolio.id
    session.add_all(
        [
            # An earlier SAP holding, sold out: its rate must not count.
            Trade(portfolio_id=pid, ticker="SAP.DE", side=TradeSide.BUY, quantity=D(5),
                  price=D(80), fx_rate=D("1.30"), ts=now - timedelta(days=300)),
            Trade(portfolio_id=pid, ticker="SAP.DE", side=TradeSide.SELL, quantity=D(5),
                  price=D(90), fx_rate=D("1.25"), realized_pnl=D(0), ts=now - timedelta(days=250)),
            # The current holding: 10 at 100 EUR, the euro at 1.10 USD.
            Trade(portfolio_id=pid, ticker="SAP.DE", side=TradeSide.BUY, quantity=D(10),
                  price=D(100), fx_rate=D("1.10"), ts=now - timedelta(days=100)),
            Trade(portfolio_id=pid, ticker="AAPL", side=TradeSide.BUY, quantity=D(10),
                  price=D(100), fx_rate=D(1), ts=now - timedelta(days=100)),
            Position(portfolio_id=pid, ticker="SAP.DE", quantity=D(10), avg_cost=D(100)),
            Position(portfolio_id=pid, ticker="AAPL", quantity=D(10), avg_cost=D(100)),
        ]
    )  # fmt: skip
    session.commit()
    return user_id


def test_gain_splits_into_price_currency_and_cross(session: Session, client: TestClient) -> None:
    user_id = _book(session)
    body = client.get("/v1/portfolio/analytics", headers=_auth_headers(user_id)).json()
    attribution = body["attribution"]
    assert attribution["method"] == "price_currency_cross" and attribution["currency"] == "USD"
    rows = {r["ticker"]: r for r in attribution["holdings"]}
    sap = rows["SAP.DE"]
    # Worked by hand: cost 10 x 100 x 1.10 = 1100; value 10 x 120 x 1.05 = 1260.
    assert D(sap["entry_rate"]) == D("1.10") and D(sap["rate_now"]) == D("1.05")
    assert D(sap["cost_base"]) == D(1100) and D(sap["value_base"]) == D(1260)
    assert D(sap["price_effect"]) == D(220)  # 10 x 20 x 1.10
    assert D(sap["currency_effect"]) == D(-50)  # 10 x 100 x -0.05
    assert D(sap["cross_effect"]) == D(-10)  # 10 x 20 x -0.05
    total = D(sap["price_effect"]) + D(sap["currency_effect"]) + D(sap["cross_effect"])
    assert total == D(sap["value_base"]) - D(sap["cost_base"])
    aapl = rows["AAPL"]
    assert D(aapl["currency_effect"]) == 0 and D(aapl["price_effect"]) == D(500)


def test_exposure_weights_nav_by_sector_country_and_currency(
    session: Session, client: TestClient
) -> None:
    user_id = _book(session)
    body = client.get("/v1/portfolio/overview", headers=_auth_headers(user_id)).json()
    nav = D(body["portfolio"]["total_value"])
    exposure = body["analytics"]["exposure"]
    assert exposure["method"] == "share_of_nav"
    dims = {d["dimension"]: {b["key"]: b for b in d["buckets"]} for d in exposure["dimensions"]}
    assert set(dims) == {"sector", "country", "currency"}
    sap_usd = D(10 * 120) * D("1.05")
    tech = dims["sector"]["Technology"]
    assert D(tech["equity_value"]) == D(1500) + sap_usd
    assert tech["weight_pct"] == float((D(1500) + sap_usd) / nav * 100)
    eur = dims["currency"]["EUR"]
    assert D(eur["equity_value"]) == sap_usd
    # Cash sits under its currency, and under "Cash" for sector and country.
    assert D(dims["currency"]["USD"]["cash_value"]) > 0
    assert "Cash" in dims["sector"] and "Cash" in dims["country"]
    assert set(dims["country"]) == {"US", "DE", "Cash"}
    for buckets in dims.values():
        assert sum(b["weight_pct"] for b in buckets.values()) == pytest.approx(100)
