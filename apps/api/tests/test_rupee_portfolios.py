"""Rupee-based portfolios (Phase 4.8).

The owner's rule (13 Nov 2026): a fresh account may switch its base
currency to INR, restarting at ₹1 crore; after any activity it is fixed.
In an INR account cash, buying power, reservations, realized P&L and NAV are
in rupees, and a USD purchase converts rupees through the USD pivot.

Rates here are round test values chosen for exact arithmetic, not market
rates: 1 INR = 0.0125 USD (80 INR per USD), 1 EUR = 1.10 USD. The app itself
converts at the stored nightly rate (`stockviz.cli fx`, yfinance INRUSD=X;
about 94 INR per USD on 12 Nov 2026).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session, col, select

from stockviz._time import utcnow
from stockviz.models import (
    FxConversion,
    FxRate,
    OrderType,
    Portfolio,
    PortfolioSnapshot,
    PriceBar,
    Symbol,
    TradeSide,
    User,
)
from stockviz.services.trading import compute_portfolio, ensure_default_portfolio, execute_trade
from stockviz.services.trading.account import (
    STARTING_CASH,
    AccountNotFresh,
    UnsupportedBaseCurrency,
    set_base_currency,
)
from stockviz.services.trading.buying_power import reserved_cash
from stockviz.services.trading.execute import InsufficientCash
from stockviz.services.trading.orders import create_pending_order
from stockviz.services.trading.snapshots import upsert_user_snapshot
from stockviz.settings import get_settings

CRORE = Decimal("10000000")


@pytest.fixture
def trader(session: Session) -> int:
    user = User(email="inr@stockviz.dev", name="Rupee")
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.id is not None
    ensure_default_portfolio(session, user.id)
    today = utcnow().date()
    for ticker, ccy, close in (
        ("RELIANCE.NS", "INR", "2500"),
        ("AAPL", "USD", "100"),
        ("SAP.DE", "EUR", "200"),
    ):
        session.add(Symbol(ticker=ticker, name=ticker, currency=ccy))
        session.commit()
        value = Decimal(close)
        session.add(
            PriceBar(
                ticker=ticker, ts=datetime.combine(today, datetime.min.time()), interval="1d",
                open=value, high=value, low=value, close=value, volume=1000, source="test",
            )
        )  # fmt: skip
    session.add(FxRate(currency="INR", date=today, usd_rate=Decimal("0.0125"), source="test"))
    session.add(FxRate(currency="EUR", date=today, usd_rate=Decimal("1.10"), source="test"))
    session.commit()
    return user.id


def _portfolio(session: Session, user_id: int) -> Portfolio:
    portfolio = session.exec(select(Portfolio).where(col(Portfolio.user_id) == user_id)).one()
    session.refresh(portfolio)
    return portfolio


def _rupee(session: Session, user_id: int) -> Portfolio:
    return set_base_currency(session, user_id=user_id, currency="INR")


def test_a_fresh_account_restarts_at_one_crore(session: Session, trader: int) -> None:
    portfolio = _rupee(session, trader)
    assert portfolio.base_currency == "INR"
    assert portfolio.cash_balance == CRORE == portfolio.opening_nav
    user = session.get(User, trader)
    assert user is not None and user.display_currency == "INR"
    # The day-zero snapshot is restated, so returns start from ₹1 crore.
    navs = {s.nav for s in session.exec(select(PortfolioSnapshot)).all()}
    assert navs == {CRORE}
    # Repeating the switch changes nothing; switching back restores $100,000.
    assert _rupee(session, trader).cash_balance == CRORE
    back = set_base_currency(session, user_id=trader, currency="usd")
    assert back.cash_balance == STARTING_CASH["USD"] and back.base_currency == "USD"


def test_the_base_is_fixed_after_the_first_trade(session: Session, trader: int) -> None:
    execute_trade(session, user_id=trader, ticker="AAPL", side=TradeSide.BUY, quantity=Decimal(1))
    with pytest.raises(AccountNotFresh, match="trades"):
        _rupee(session, trader)
    assert _portfolio(session, trader).base_currency == "USD"
    with pytest.raises(UnsupportedBaseCurrency):
        set_base_currency(session, user_id=trader, currency="EUR")


def test_an_nse_trade_runs_end_to_end_in_rupees(session: Session, trader: int) -> None:
    """Phase 4's acceptance, literally: one NSE instrument, INR throughout."""
    _rupee(session, trader)
    buy = execute_trade(
        session, user_id=trader, ticker="RELIANCE.NS", side=TradeSide.BUY, quantity=Decimal(100)
    )
    assert buy.fx_rate == 1 and buy.base_currency == "INR"
    assert buy.base_cost == Decimal("250000")
    assert _portfolio(session, trader).cash_balance == CRORE - Decimal("250000")
    assert session.exec(select(FxConversion)).first() is None  # nothing converted

    bar = session.exec(select(PriceBar).where(PriceBar.ticker == "RELIANCE.NS")).one()
    bar.close = bar.high = Decimal("2600")
    session.add(bar)
    session.commit()
    sell = execute_trade(
        session, user_id=trader, ticker="RELIANCE.NS", side=TradeSide.SELL, quantity=Decimal(100)
    )
    assert sell.realized_pnl == Decimal("10000")  # 100 x ₹100, in rupees
    assert _portfolio(session, trader).cash_balance == CRORE + Decimal("10000")


def test_a_us_buy_converts_rupees_through_the_dollar(session: Session, trader: int) -> None:
    _rupee(session, trader)
    result = execute_trade(
        session, user_id=trader, ticker="AAPL", side=TradeSide.BUY, quantity=Decimal(10)
    )
    assert result.fx_rate == Decimal(80)  # INR per USD
    assert result.base_cost == Decimal("80000")  # 10 x $100 x 80
    assert _portfolio(session, trader).cash_balance == CRORE - Decimal("80000")
    conversion = session.exec(select(FxConversion)).one()
    assert (conversion.from_currency, conversion.to_currency) == ("INR", "USD")
    assert conversion.from_amount == Decimal("80000") and conversion.to_amount == Decimal("1000")

    # A cross-rate: EUR priced in rupees through USD (1.10 / 0.0125 = 88).
    sap = execute_trade(
        session, user_id=trader, ticker="SAP.DE", side=TradeSide.BUY, quantity=Decimal(1)
    )
    assert sap.fx_rate == Decimal(88) and sap.base_cost == Decimal("17600")


def test_buying_power_and_reservations_are_in_rupees(session: Session, trader: int) -> None:
    _rupee(session, trader)
    create_pending_order(
        session, user_id=trader, ticker="AAPL", side=TradeSide.BUY,
        order_type=OrderType.LIMIT, quantity=Decimal(100), limit_price=Decimal(90),
    )  # fmt: skip
    portfolio = _portfolio(session, trader)
    assert portfolio.id is not None
    assert reserved_cash(session, portfolio.id) == Decimal("720000")  # 100 x $90 x 80
    # ₹1 crore less the reservation leaves ₹92.8 lakh; ₹1 crore of AAPL is refused.
    with pytest.raises(InsufficientCash, match=r"INR 9,280,000\.00"):
        execute_trade(
            session, user_id=trader, ticker="AAPL", side=TradeSide.BUY, quantity=Decimal(1250)
        )


def test_valuation_and_snapshots_are_in_rupees(session: Session, trader: int) -> None:
    _rupee(session, trader)
    execute_trade(session, user_id=trader, ticker="AAPL", side=TradeSide.BUY, quantity=Decimal(10))
    portfolio = _portfolio(session, trader)
    valuation = compute_portfolio(session, portfolio, display_currency="INR")
    assert valuation.base_currency == "INR"
    assert valuation.total_value == CRORE  # ₹80,000 moved from cash into AAPL
    in_usd = compute_portfolio(session, portfolio, display_currency="USD")
    assert in_usd.total_value == CRORE * Decimal("0.0125")  # $125,000

    snap = upsert_user_snapshot(session, user_id=trader, snapshot_date=utcnow().date())
    assert snap.nav == CRORE  # in the base, like opening_nav


def test_the_endpoint_switches_once_and_then_refuses(
    session: Session, trader: int, client: TestClient
) -> None:
    token = jose_jwt.encode({"sub": str(trader)}, get_settings().internal_api_token, "HS256")
    headers = {"Authorization": f"Bearer {token}"}

    fresh = client.get("/v1/portfolio", headers=headers).json()
    assert fresh["base_currency"] == "USD" and fresh["base_currency_locked"] is False

    switched = client.put(
        "/v1/portfolio/base-currency", json={"base_currency": "INR"}, headers=headers
    )
    assert switched.status_code == 200, switched.text
    body = switched.json()
    assert body["base_currency"] == "INR" and body["display_currency"] == "INR"
    assert Decimal(body["available_cash"]) == CRORE

    trade = client.post(
        "/v1/trades",
        json={"ticker": "RELIANCE.NS", "side": "buy", "quantity": "4"},
        headers=headers,
    ).json()
    assert trade["base_currency"] == "INR" and Decimal(trade["total_base"]) == Decimal("10000")
    assert Decimal(trade["total_usd"]) == Decimal("125")  # ₹10,000 x 0.0125

    assert client.get("/v1/portfolio", headers=headers).json()["base_currency_locked"] is True
    again = client.put(
        "/v1/portfolio/base-currency", json={"base_currency": "USD"}, headers=headers
    )
    assert again.status_code == 409
    assert client.put(
        "/v1/portfolio/base-currency", json={"base_currency": "GBP"}, headers=headers
    ).status_code in (400, 409)
