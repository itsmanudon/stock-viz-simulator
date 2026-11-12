"""Cash per currency (Phase 4.5b, design note option B).

A sale of SAP.DE used to convert its EUR proceeds straight back to USD; a buy
always converted the whole cost. Now a sale keeps EUR, a buy spends EUR first,
and only a shortfall converts from USD, with a conversion row for it.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest
from sqlmodel import Session, col, select

from stockviz._time import utcnow
from stockviz.models import (
    CashBalance,
    FxConversion,
    FxRate,
    Portfolio,
    PriceBar,
    Symbol,
    Trade,
    TradeSide,
    User,
)
from stockviz.services.trading import compute_portfolio, ensure_default_portfolio, execute_trade
from stockviz.services.trading.execute import InsufficientCash

RATE = Decimal("1.10")  # USD per EUR


@pytest.fixture
def trader(session: Session) -> int:
    user = User(email="eur@stockviz.dev", name="Euro")
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.id is not None
    ensure_default_portfolio(session, user.id)
    today = utcnow().date()
    session.add(Symbol(ticker="SAP.DE", name="SAP", currency="EUR"))
    session.add(Symbol(ticker="AAPL", name="Apple", currency="USD"))
    session.commit()
    for ticker, close in (("SAP.DE", "200"), ("AAPL", "100")):
        value = Decimal(close)
        session.add(
            PriceBar(
                ticker=ticker,
                ts=datetime.combine(today, datetime.min.time()),
                interval="1d",
                open=value,
                high=value,
                low=value,
                close=value,
                volume=1000,
                source="test",
            )
        )
    session.add(FxRate(currency="EUR", date=today, usd_rate=RATE, source="test"))
    session.commit()
    return user.id


def _portfolio(session: Session, user_id: int) -> Portfolio:
    portfolio = session.exec(select(Portfolio).where(col(Portfolio.user_id) == user_id)).one()
    session.refresh(portfolio)
    return portfolio


def _eur(session: Session, portfolio: Portfolio) -> Decimal:
    row = session.exec(
        select(CashBalance).where(
            col(CashBalance.portfolio_id) == portfolio.id, col(CashBalance.currency) == "EUR"
        )
    ).first()
    return row.amount if row is not None else Decimal(0)


def _trade(session: Session, user_id: int, side: TradeSide, qty: int, ticker: str = "SAP.DE"):
    return execute_trade(session, user_id=user_id, ticker=ticker, side=side, quantity=Decimal(qty))


def test_a_buy_with_no_euros_converts_the_whole_cost(session: Session, trader: int) -> None:
    start = _portfolio(session, trader).cash_balance
    result = _trade(session, trader, TradeSide.BUY, 10)

    portfolio = _portfolio(session, trader)
    assert portfolio.cash_balance == start - Decimal("2200")  # 10 x 200 EUR x 1.10
    assert _eur(session, portfolio) == 0
    conversion = session.exec(select(FxConversion)).one()
    assert (conversion.from_currency, conversion.to_currency) == ("USD", "EUR")
    assert (conversion.from_amount, conversion.to_amount) == (Decimal("2200"), Decimal("2000"))
    assert conversion.rate == RATE and conversion.reason == "buy"
    assert conversion.trade_id == result.trade.id


def test_a_sale_keeps_its_euros(session: Session, trader: int) -> None:
    _trade(session, trader, TradeSide.BUY, 10)
    usd_after_buy = _portfolio(session, trader).cash_balance

    _trade(session, trader, TradeSide.SELL, 4)

    portfolio = _portfolio(session, trader)
    assert portfolio.cash_balance == usd_after_buy
    assert _eur(session, portfolio) == Decimal("800")


def test_a_buy_spends_euros_first_then_converts_the_shortfall(
    session: Session, trader: int
) -> None:
    _trade(session, trader, TradeSide.BUY, 10)
    _trade(session, trader, TradeSide.SELL, 4)  # 800 EUR held
    usd_before = _portfolio(session, trader).cash_balance

    _trade(session, trader, TradeSide.BUY, 5)  # 1,000 EUR: 800 held + 200 converted

    portfolio = _portfolio(session, trader)
    assert _eur(session, portfolio) == 0
    assert portfolio.cash_balance == usd_before - Decimal("220")
    latest = session.exec(select(FxConversion).order_by(col(FxConversion.id).desc())).first()
    assert latest is not None and latest.to_amount == Decimal("200")


def test_a_buy_covered_by_euros_converts_nothing(session: Session, trader: int) -> None:
    _trade(session, trader, TradeSide.BUY, 10)
    _trade(session, trader, TradeSide.SELL, 10)  # 2,000 EUR held
    usd_before = _portfolio(session, trader).cash_balance

    _trade(session, trader, TradeSide.BUY, 3)

    portfolio = _portfolio(session, trader)
    assert portfolio.cash_balance == usd_before
    assert _eur(session, portfolio) == Decimal("1400")
    assert len(session.exec(select(FxConversion)).all()) == 1  # only the first buy


def test_valuation_counts_foreign_cash(session: Session, trader: int) -> None:
    _trade(session, trader, TradeSide.BUY, 10)
    _trade(session, trader, TradeSide.SELL, 10)
    portfolio = _portfolio(session, trader)

    valuation = compute_portfolio(session, portfolio)

    by_ccy = {c.currency: (c.amount, c.value) for c in valuation.cash_by_currency}
    assert by_ccy["EUR"] == (Decimal("2000"), Decimal("2200"))
    assert by_ccy["USD"][0] == portfolio.cash_balance
    assert valuation.cash_balance == portfolio.cash_balance + Decimal("2200")
    assert valuation.available_cash == portfolio.cash_balance  # base buying power only
    assert valuation.total_value == valuation.cash_balance + valuation.market_value


def test_a_short_base_balance_refuses_the_buy_and_changes_nothing(
    session: Session, trader: int
) -> None:
    portfolio = _portfolio(session, trader)
    start = portfolio.cash_balance
    too_many = int(start / Decimal("220")) + 1

    with pytest.raises(InsufficientCash):
        _trade(session, trader, TradeSide.BUY, too_many)
    session.rollback()

    portfolio = _portfolio(session, trader)
    assert portfolio.cash_balance == start
    assert session.exec(select(FxConversion)).all() == []
    assert session.exec(select(Trade)).all() == []


def test_usd_trades_are_unchanged(session: Session, trader: int) -> None:
    start = _portfolio(session, trader).cash_balance
    _trade(session, trader, TradeSide.BUY, 10, ticker="AAPL")
    _trade(session, trader, TradeSide.SELL, 4, ticker="AAPL")

    portfolio = _portfolio(session, trader)
    assert portfolio.cash_balance == start - Decimal("600")
    assert session.exec(select(CashBalance)).all() == []
    assert session.exec(select(FxConversion)).all() == []
