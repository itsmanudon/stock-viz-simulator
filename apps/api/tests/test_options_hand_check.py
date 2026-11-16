"""Phase 9 acceptance: the worked figures in docs/benchmarks/2026-11-16-options-hand-check.md.

"A covered call and a vertical spread can be modelled, traded on paper and settled."
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlmodel import Session, select

from stockviz.models import (
    OptionCover,
    OptionSide,
    OptionsPosition,
    OptionStatus,
    OptionStrategy,
    OptionType,
    Portfolio,
    Trade,
)
from stockviz.models.portfolio import TradeSide
from stockviz.services.options import settle_expired_options
from stockviz.services.options.pricing import black_scholes, implied_volatility
from stockviz.services.trading import DEFAULT_STARTING_CASH, ensure_default_portfolio
from stockviz.services.trading.buying_power import available_cash, available_shares
from tests.test_option_short_legs import _hold
from tests.test_options import EXPIRY_SESSION, TODAY, _make_user, _seed_bars

D = Decimal
EXPIRED = TODAY - timedelta(days=1)  # a Sunday; the Friday close settles it


@pytest.fixture(autouse=True)
def option_clock(monkeypatch):
    monkeypatch.setattr("stockviz.services.options.trade.utcnow", lambda: datetime(2026, 8, 24, 18))


# 1. One price, its Greeks, and implied volatility --------------------------


def test_section_1_black_scholes_and_greeks() -> None:
    call = black_scholes(
        spot=100, strike=105, time_to_expiry_years=0.25, volatility=0.2,
        risk_free_rate=0.05, option_type="call",
    )  # fmt: skip
    put = black_scholes(
        spot=100, strike=105, time_to_expiry_years=0.25, volatility=0.2,
        risk_free_rate=0.05, option_type="put",
    )  # fmt: skip
    worksheet = {
        "value": 2.477902, "delta": 0.377178, "gamma": 0.037988,
        "vega": 18.994145, "theta": -0.025643, "rho": 8.809967,
    }  # fmt: skip
    for name, expected in worksheet.items():
        assert getattr(call, name) == pytest.approx(expected, abs=1e-6), name
    assert put.value == pytest.approx(6.173571, abs=1e-6)
    solved = implied_volatility(
        price=2.477902, spot=100, strike=105, time_to_expiry_years=0.25,
        risk_free_rate=0.05, option_type="call",
    )  # fmt: skip
    assert solved.volatility == pytest.approx(0.20, abs=1e-6)


# Settlement fixtures ---------------------------------------------------------


def _account(session: Session, close: float) -> tuple[int, int]:
    _seed_bars(session, [close], end=EXPIRY_SESSION)
    user_id = _make_user(session)
    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.id is not None
    return user_id, portfolio.id


def _leg(session: Session, user_id: int, portfolio_id: int, **fields) -> OptionsPosition:
    leg = OptionsPosition(
        user_id=user_id, portfolio_id=portfolio_id, ticker="AAPL",
        expiry=EXPIRED, quantity=fields.pop("quantity", 1), **fields,
    )  # fmt: skip
    session.add(leg)
    session.flush()
    return leg


def _spread(
    session: Session, close: float, kind: str, *, long_k: int, short_k: int,
    long_premium: int, short_premium: int, collateral: int = 0,
) -> tuple[int, int, OptionStrategy, OptionsPosition, OptionsPosition]:  # fmt: skip
    user_id, portfolio_id = _account(session, close)
    strategy = OptionStrategy(
        user_id=user_id, portfolio_id=portfolio_id, kind=kind,
        net_premium=D(short_premium - long_premium), collateral=D(collateral),
    )  # fmt: skip
    session.add(strategy)
    session.flush()
    long_leg = _leg(
        session, user_id, portfolio_id, option_type=OptionType.CALL, strike=D(long_k),
        premium_paid=D(long_premium), strategy_id=strategy.id,
    )  # fmt: skip
    short_leg = _leg(
        session, user_id, portfolio_id, option_type=OptionType.CALL, strike=D(short_k),
        premium_paid=D(short_premium), side=OptionSide.SHORT, cover=OptionCover.LEG,
        covering_leg_id=long_leg.id, strategy_id=strategy.id,
    )  # fmt: skip
    session.commit()
    return user_id, portfolio_id, strategy, long_leg, short_leg


def _cash(session: Session, portfolio_id: int) -> Decimal:
    portfolio = session.get(Portfolio, portfolio_id)
    assert portfolio is not None
    session.refresh(portfolio)
    return portfolio.cash_balance


# 2. Covered call -----------------------------------------------------------


def _covered_call(session: Session, close: float) -> tuple[int, OptionsPosition]:
    user_id, portfolio_id = _account(session, close)
    _hold(session, portfolio_id, 200, avg_cost="90")
    leg = _leg(
        session, user_id, portfolio_id, option_type=OptionType.CALL, strike=D(110),
        premium_paid=D(500), quantity=2, side=OptionSide.SHORT, cover=OptionCover.SHARES,
    )  # fmt: skip
    session.commit()
    assert available_shares(session, portfolio_id, "AAPL") == D(0)
    return portfolio_id, leg


def test_section_2_covered_call_assigned_at_120(session: Session) -> None:
    portfolio_id, leg = _covered_call(session, 120.0)
    settle_expired_options(session, settle_date=TODAY)
    session.refresh(leg)
    assert (leg.status, leg.realized_pnl) == (OptionStatus.EXERCISED, D(500))
    (trade,) = session.exec(select(Trade).where(Trade.portfolio_id == portfolio_id)).all()
    assert (trade.side, trade.quantity, trade.price, trade.realized_pnl) == (
        TradeSide.SELL, D(200), D(110), D(4000),
    )  # fmt: skip
    assert _cash(session, portfolio_id) == DEFAULT_STARTING_CASH + D(22_000)


def test_section_2_covered_call_expires_at_105(session: Session) -> None:
    portfolio_id, leg = _covered_call(session, 105.0)
    settle_expired_options(session, settle_date=TODAY)
    session.refresh(leg)
    assert (leg.status, leg.realized_pnl) == (OptionStatus.EXPIRED, D(500))
    assert available_shares(session, portfolio_id, "AAPL") == D(200)
    assert _cash(session, portfolio_id) == DEFAULT_STARTING_CASH


# 3. Bull call spread ---------------------------------------------------------


@pytest.mark.parametrize(
    ("close", "net_cash", "realized"),
    [(115.0, 1000, 600), (105.0, 500, 100), (95.0, 0, -400)],
)
def test_section_3_bull_call_spread(
    session: Session, close: float, net_cash: int, realized: int
) -> None:
    _, portfolio_id, strategy, long_leg, short_leg = _spread(
        session, close, "bull_call", long_k=100, short_k=110, long_premium=600,
        short_premium=200,
    )  # fmt: skip
    cash_before = _cash(session, portfolio_id)
    assert settle_expired_options(session, settle_date=TODAY) == 2
    session.refresh(long_leg)
    session.refresh(short_leg)
    session.refresh(strategy)
    assert _cash(session, portfolio_id) == cash_before + D(net_cash)
    assert (long_leg.realized_pnl or 0) + (short_leg.realized_pnl or 0) == D(realized)
    assert strategy.status == "settled"
    # Nothing goes through the equity book: a spread settles in cash.
    assert session.exec(select(Trade).where(Trade.portfolio_id == portfolio_id)).first() is None


# 4. Bear call spread (credit) -----------------------------------------------


def test_section_4_bear_call_spread_pays_from_its_held_back_cash(session: Session) -> None:
    _, portfolio_id, _strategy, long_leg, short_leg = _spread(
        session, 115.0, "bear_call", long_k=110, short_k=100, long_premium=200,
        short_premium=600, collateral=1000,
    )  # fmt: skip
    portfolio = session.get(Portfolio, portfolio_id)
    assert portfolio is not None
    cash_before = portfolio.cash_balance
    assert available_cash(session, portfolio) == cash_before - D(1000)
    settle_expired_options(session, settle_date=TODAY)
    session.refresh(long_leg)
    session.refresh(short_leg)
    assert short_leg.realized_pnl == D(-900)
    assert long_leg.realized_pnl == D(300)
    assert _cash(session, portfolio_id) == cash_before - D(1000)
    session.refresh(portfolio)
    assert available_cash(session, portfolio) == portfolio.cash_balance  # released
