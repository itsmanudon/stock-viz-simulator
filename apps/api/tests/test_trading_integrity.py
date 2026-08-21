"""Regression tests for the financial-integrity fixes.

Each test here pins a behaviour that was previously wrong:

- Pending-order settlement ignored FX, debiting native-currency amounts from
  the USD cash bucket.
- Dividend crediting did the same.
- Options were invisible to portfolio valuation, so NAV dropped by the premium
  and never recorded the offsetting asset.
- Triggered orders that could not fill were cancelled with no reason.
- Settlement would fill against a stale close if the price refresh had failed.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlmodel import Session, select

from stockviz.models import (
    Dividend,
    FxRate,
    OptionsPosition,
    OptionStatus,
    OptionType,
    PendingOrder,
    Portfolio,
    Position,
    PriceBar,
    Symbol,
    Trade,
    TradeSide,
    User,
)
from stockviz.models.order import OrderStatus, OrderType
from stockviz.services.trading import (
    compute_portfolio,
    credit_due_dividends,
    ensure_default_portfolio,
    execute_trade,
    settle_pending_orders,
)

BAR_DATE = datetime(2025, 4, 10)
BAR_DAY = BAR_DATE.date()


def _user(session: Session, email: str = "fx@stockviz.dev") -> int:
    user = User(email=email, name="FX Trader")
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.id is not None
    return user.id


def _symbol(
    session: Session,
    ticker: str,
    *,
    currency: str = "USD",
    close: Decimal = Decimal("100"),
    ts: datetime = BAR_DATE,
) -> None:
    session.add(Symbol(ticker=ticker, name=f"{ticker} Inc.", currency=currency))
    session.commit()
    session.add(
        PriceBar(
            ticker=ticker,
            ts=ts,
            interval="1d",
            open=close,
            high=close,
            low=close,
            close=close,
            volume=1_000,
            source="test",
        )
    )
    session.commit()


def _fx(session: Session, currency: str, usd_rate: str, on: date = BAR_DAY) -> None:
    session.add(FxRate(currency=currency, date=on, usd_rate=Decimal(usd_rate), source="test"))
    session.commit()


# --------------------------------------------------------------------------
# FX in pending-order settlement
# --------------------------------------------------------------------------


def test_pending_order_fill_converts_native_price_to_usd_cash(session: Session) -> None:
    """A GBP limit order must debit USD, not pounds-as-dollars."""
    user_id = _user(session)
    _symbol(session, "BARC.L", currency="GBP", close=Decimal("100"))
    _fx(session, "GBP", "1.25")

    portfolio = ensure_default_portfolio(session, user_id)
    opening_cash = portfolio.cash_balance
    assert portfolio.id is not None

    session.add(
        PendingOrder(
            portfolio_id=portfolio.id,
            ticker="BARC.L",
            side=TradeSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal(10),
            limit_price=Decimal("150"),  # close 100 <= 150, so it triggers
        )
    )
    session.commit()

    filled = settle_pending_orders(session, session_date=BAR_DAY)
    assert filled == 1

    session.refresh(portfolio)
    # 10 shares x GBP 100 = GBP 1000 -> USD 1250 at 1.25.
    assert opening_cash - portfolio.cash_balance == Decimal("1250.000000")

    trade = session.exec(select(Trade)).one()
    assert trade.price == Decimal("100.000000")  # native currency on the row
    assert trade.fx_rate == Decimal("1.25000000")


def test_pending_order_fill_matches_market_order_cash_effect(session: Session) -> None:
    """The two fill paths must agree — they share ``apply_fill``."""
    market_user = _user(session, "market@stockviz.dev")
    limit_user = _user(session, "limit@stockviz.dev")
    _symbol(session, "SAP.DE", currency="EUR", close=Decimal("80"))
    _fx(session, "EUR", "1.10")

    execute_trade(
        session, user_id=market_user, ticker="SAP.DE", side=TradeSide.BUY, quantity=Decimal(5)
    )

    limit_portfolio = ensure_default_portfolio(session, limit_user)
    assert limit_portfolio.id is not None
    session.add(
        PendingOrder(
            portfolio_id=limit_portfolio.id,
            ticker="SAP.DE",
            side=TradeSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal(5),
            limit_price=Decimal("90"),
        )
    )
    session.commit()
    settle_pending_orders(session, session_date=BAR_DAY)

    market_portfolio = session.exec(select(Portfolio).where(Portfolio.user_id == market_user)).one()
    session.refresh(limit_portfolio)
    assert market_portfolio.cash_balance == limit_portfolio.cash_balance


# --------------------------------------------------------------------------
# Stale-close guard + cancel reasons
# --------------------------------------------------------------------------


def test_settlement_skips_when_latest_bar_is_stale(session: Session) -> None:
    """A failed price refresh must leave orders pending, not fill on old data."""
    user_id = _user(session)
    _symbol(session, "AAPL", close=Decimal("100"))

    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.id is not None
    session.add(
        PendingOrder(
            portfolio_id=portfolio.id,
            ticker="AAPL",
            side=TradeSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal(1),
            limit_price=Decimal("150"),
        )
    )
    session.commit()

    # Today's session is a day after the newest bar we have.
    filled = settle_pending_orders(session, session_date=BAR_DAY + timedelta(days=1))
    assert filled == 0
    order = session.exec(select(PendingOrder)).one()
    assert order.status == OrderStatus.PENDING


def test_unfillable_order_records_a_cancel_reason(session: Session) -> None:
    user_id = _user(session)
    _symbol(session, "AAPL", close=Decimal("100"))

    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.id is not None
    # Sell an position the portfolio doesn't hold.
    session.add(
        PendingOrder(
            portfolio_id=portfolio.id,
            ticker="AAPL",
            side=TradeSide.SELL,
            order_type=OrderType.TAKE_PROFIT,
            quantity=Decimal(5),
            limit_price=Decimal("50"),  # close 100 >= 50, triggers
        )
    )
    session.commit()

    assert settle_pending_orders(session, session_date=BAR_DAY) == 0
    order = session.exec(select(PendingOrder)).one()
    assert order.status == OrderStatus.CANCELLED
    assert order.cancel_reason is not None
    assert "cannot sell" in order.cancel_reason


# --------------------------------------------------------------------------
# FX in dividend crediting
# --------------------------------------------------------------------------


def test_dividend_credit_converts_to_usd(session: Session) -> None:
    user_id = _user(session)
    _symbol(session, "BARC.L", currency="GBP", close=Decimal("100"))
    _fx(session, "GBP", "1.25")

    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.id is not None
    session.add(
        Position(
            portfolio_id=portfolio.id,
            ticker="BARC.L",
            quantity=Decimal(100),
            avg_cost=Decimal("90"),
        )
    )
    session.add(Dividend(ticker="BARC.L", ex_date=BAR_DAY, amount=Decimal("2")))
    session.commit()
    opening_cash = portfolio.cash_balance

    assert credit_due_dividends(session, credit_date=BAR_DAY) == 1
    session.refresh(portfolio)
    # 100 shares x GBP 2 = GBP 200 -> USD 250.
    assert portfolio.cash_balance - opening_cash == Decimal("250.000000")


def test_dividend_credit_skips_symbol_without_fx_rate(session: Session) -> None:
    """No rate means we cannot value the payout — skip rather than credit 1:1."""
    user_id = _user(session)
    _symbol(session, "BARC.L", currency="GBP", close=Decimal("100"))
    # deliberately no FX rate

    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.id is not None
    session.add(
        Position(
            portfolio_id=portfolio.id,
            ticker="BARC.L",
            quantity=Decimal(100),
            avg_cost=Decimal("90"),
        )
    )
    session.add(Dividend(ticker="BARC.L", ex_date=BAR_DAY, amount=Decimal("2")))
    session.commit()
    opening_cash = portfolio.cash_balance

    assert credit_due_dividends(session, credit_date=BAR_DAY) == 0
    session.refresh(portfolio)
    assert portfolio.cash_balance == opening_cash


# --------------------------------------------------------------------------
# Options in NAV
# --------------------------------------------------------------------------


def test_open_option_is_counted_in_portfolio_value(session: Session) -> None:
    """NAV must include the option's mark-to-model value, not just lose the premium."""
    user_id = _user(session)
    _symbol(session, "AAPL", close=Decimal("150"))

    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.id is not None
    premium = Decimal("500.00")
    portfolio.cash_balance = portfolio.cash_balance - premium
    session.add(portfolio)
    session.add(
        OptionsPosition(
            user_id=user_id,
            portfolio_id=portfolio.id,
            ticker="AAPL",
            option_type=OptionType.CALL,
            strike=Decimal("100"),  # deep ITM against a 150 spot
            expiry=BAR_DAY + timedelta(days=90),
            quantity=1,
            premium_paid=premium,
            status=OptionStatus.OPEN,
        )
    )
    session.commit()

    snap = compute_portfolio(session, portfolio)
    assert len(snap.option_positions) == 1
    # A deep-ITM call is worth roughly (spot - strike) x 100 = ~5000.
    assert snap.options_market_value > Decimal("4000")
    assert snap.total_value == snap.cash_balance + snap.market_value + snap.options_market_value


def test_closed_option_is_excluded_from_portfolio_value(session: Session) -> None:
    user_id = _user(session)
    _symbol(session, "AAPL", close=Decimal("150"))

    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.id is not None
    session.add(
        OptionsPosition(
            user_id=user_id,
            portfolio_id=portfolio.id,
            ticker="AAPL",
            option_type=OptionType.CALL,
            strike=Decimal("100"),
            expiry=BAR_DAY + timedelta(days=90),
            quantity=1,
            premium_paid=Decimal("500.00"),
            status=OptionStatus.CLOSED,
        )
    )
    session.commit()

    snap = compute_portfolio(session, portfolio)
    assert snap.option_positions == []
    assert snap.options_market_value == Decimal(0)


# --------------------------------------------------------------------------
# Realized P&L + opening snapshot
# --------------------------------------------------------------------------


def test_sell_records_realized_pnl(session: Session) -> None:
    user_id = _user(session)
    _symbol(session, "AAPL", close=Decimal("150"))

    execute_trade(session, user_id=user_id, ticker="AAPL", side=TradeSide.BUY, quantity=Decimal(10))
    # Price rises to 170, then we sell half.
    session.add(
        PriceBar(
            ticker="AAPL",
            ts=BAR_DATE + timedelta(days=1),
            interval="1d",
            open=Decimal("170"),
            high=Decimal("170"),
            low=Decimal("170"),
            close=Decimal("170"),
            volume=1_000,
            source="test",
        )
    )
    session.commit()

    result = execute_trade(
        session, user_id=user_id, ticker="AAPL", side=TradeSide.SELL, quantity=Decimal(5)
    )
    # (170 - 150) x 5 = 100.
    assert result.realized_pnl == Decimal("100.000000")

    buys = session.exec(select(Trade).where(Trade.side == TradeSide.BUY)).all()
    assert all(t.realized_pnl is None for t in buys)


def test_new_portfolio_seeds_an_opening_snapshot(session: Session) -> None:
    """Return-since-inception should measure from funding, not from the first
    time the nightly snapshot job happened to run."""
    from stockviz.models import PortfolioSnapshot

    user_id = _user(session)
    ensure_default_portfolio(session, user_id)

    snapshots = session.exec(
        select(PortfolioSnapshot).where(PortfolioSnapshot.user_id == user_id)
    ).all()
    assert len(snapshots) == 1
    assert snapshots[0].nav == Decimal("100000.00")
