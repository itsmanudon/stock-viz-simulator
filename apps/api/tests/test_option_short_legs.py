"""Phase 9.2: covered short legs (covered calls, cash-secured puts) and their margin."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from stockviz._time import utcnow
from stockviz.models import (
    OptionCover,
    OptionSide,
    OptionsPosition,
    OptionStatus,
    OptionType,
    Position,
    Symbol,
    Trade,
)
from stockviz.models.portfolio import TradeSide
from stockviz.services.options import (
    InsufficientCoverForOption,
    close_option,
    open_option,
    settle_expired_options,
)
from stockviz.services.options.margin import (
    cash_secured_put,
    covered_call,
    long_option,
)
from stockviz.services.trading import DEFAULT_STARTING_CASH, ensure_default_portfolio
from stockviz.services.trading.buying_power import available_cash, available_shares
from stockviz.services.trading.execute import InsufficientPosition, execute_trade
from tests.test_options import (
    EXPIRY_SESSION,
    TODAY,
    _auth_headers,
    _make_user,
    _seed_bars,
)

D = Decimal
PRICES = [100 + (i % 7) for i in range(40)]  # spot 104 (39 % 7 = 4)
EXPIRY = TODAY + timedelta(days=30)


@pytest.fixture(autouse=True)
def option_clock(monkeypatch):
    monkeypatch.setattr("stockviz.services.options.trade.utcnow", lambda: datetime(2026, 8, 24, 18))


def _hold(session: Session, portfolio_id: int, shares: int, avg_cost: str = "90") -> None:
    session.add(
        Position(portfolio_id=portfolio_id, ticker="AAPL", quantity=D(shares), avg_cost=D(avg_cost))
    )
    session.commit()


def _account(session: Session, *, shares: int = 0) -> tuple[int, int]:
    _seed_bars(session, PRICES, end=TODAY - timedelta(days=1))
    user_id = _make_user(session)
    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.id is not None
    if shares:
        _hold(session, portfolio.id, shares)
    return user_id, portfolio.id


def _write(session: Session, user_id: int, option_type: OptionType, strike: str, qty: int = 1):
    return open_option(
        session,
        user_id=user_id,
        ticker="AAPL",
        option_type=option_type,
        strike=D(strike),
        expiry=EXPIRY,
        quantity=qty,
        side=OptionSide.SHORT,
    )


# ---------------------------------------------------------------------------
# margin.py: the figures, worked by hand
# ---------------------------------------------------------------------------


def test_margin_figures_by_hand() -> None:
    # Covered call, 100 shares at 100, strike 110, premium 2: keeps the 2,
    # gains stop at 110 (10 + 2 a share), breakeven 98, loss if the stock goes to 0: 98.
    cc = covered_call(strike=D(110), premium=D(2), shares=D(100), spot=D(100))
    assert (cc.collateral, cc.shares_reserved) == (D(0), D(100))
    assert (cc.max_gain, cc.max_loss, cc.breakeven) == (D("1200.00"), D("9800.00"), D("98.00"))
    # Cash-secured put, strike 95, premium 3: reserves the 9,500 assignment
    # costs; the most it can lose is that less the premium, 9,200.
    csp = cash_secured_put(strike=D(95), premium=D(3), shares=D(100))
    assert (csp.collateral, csp.max_loss, csp.max_gain) == (D("9500.00"), D("9200.00"), D("300.00"))
    assert csp.breakeven == D("92.00")
    # Long legs reserve nothing; the premium is the most they can lose.
    call = long_option(option_type="call", strike=D(100), premium=D(5), shares=D(100))
    assert (call.collateral, call.max_loss, call.max_gain, call.breakeven) == (
        D(0), D("500.00"), None, D("105.00"),
    )  # fmt: skip
    put = long_option(option_type="put", strike=D(100), premium=D(5), shares=D(100))
    assert (put.max_gain, put.breakeven) == (D("9500.00"), D("95.00"))


# ---------------------------------------------------------------------------
# Writing: covered or refused
# ---------------------------------------------------------------------------


def test_an_uncovered_call_is_refused(session: Session) -> None:
    user_id, _ = _account(session, shares=150)
    with pytest.raises(InsufficientCoverForOption, match="needs 200 AAPL shares"):
        _write(session, user_id, OptionType.CALL, "110", qty=2)
    assert session.exec(select(OptionsPosition)).first() is None


def test_a_covered_call_credits_the_premium_and_reserves_the_shares(session: Session) -> None:
    user_id, portfolio_id = _account(session, shares=250)
    result = _write(session, user_id, OptionType.CALL, "110", qty=2)
    position = result.position
    assert (position.side, position.cover) == (OptionSide.SHORT, OptionCover.SHARES)
    assert result.cash_delta == position.premium_paid > 0
    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.cash_balance == DEFAULT_STARTING_CASH + position.premium_paid
    assert available_shares(session, portfolio_id, "AAPL") == D(50)
    # The reserved shares cannot be sold, nor cover a second call.
    with pytest.raises(InsufficientPosition, match="covered calls"):
        execute_trade(session, user_id=user_id, ticker="AAPL", side=TradeSide.SELL, quantity=D(51))
    session.rollback()
    with pytest.raises(InsufficientCoverForOption):
        _write(session, user_id, OptionType.CALL, "110", qty=1)
    session.rollback()
    execute_trade(session, user_id=user_id, ticker="AAPL", side=TradeSide.SELL, quantity=D(50))


def test_a_cash_secured_put_reserves_its_strike_value(session: Session) -> None:
    user_id, _ = _account(session)
    position = _write(session, user_id, OptionType.PUT, "100", qty=3).position
    assert (position.side, position.cover) == (OptionSide.SHORT, OptionCover.CASH)
    portfolio = ensure_default_portfolio(session, user_id)
    premium = position.premium_paid
    assert portfolio.cash_balance == DEFAULT_STARTING_CASH + premium
    # The premium stays spendable; the 30,000 assignment would cost does not.
    assert available_cash(session, portfolio) == DEFAULT_STARTING_CASH + premium - D(30_000)


def test_a_put_the_cash_cannot_secure_is_refused(session: Session) -> None:
    user_id, _ = _account(session)
    with pytest.raises(InsufficientCoverForOption, match="cash-secured put reserves"):
        _write(session, user_id, OptionType.PUT, "100", qty=20)  # 200,000 of strike value


def test_the_database_refuses_a_naked_short(session: Session) -> None:
    user_id, portfolio_id = _account(session)
    session.add(
        OptionsPosition(
            user_id=user_id, portfolio_id=portfolio_id, ticker="AAPL",
            option_type=OptionType.CALL, strike=D(110), expiry=EXPIRY, quantity=1,
            premium_paid=D(100), side=OptionSide.SHORT, cover=None,
        )
    )  # fmt: skip
    with pytest.raises(IntegrityError):
        session.commit()


# ---------------------------------------------------------------------------
# Buying back
# ---------------------------------------------------------------------------


def test_buying_back_a_covered_call_releases_the_shares(session: Session) -> None:
    user_id, portfolio_id = _account(session, shares=100)
    position = _write(session, user_id, OptionType.CALL, "110").position
    premium = position.premium_paid
    cash_after_write = ensure_default_portfolio(session, user_id).cash_balance
    result = close_option(session, user_id=user_id, option_id=position.id)  # type: ignore[arg-type]
    cost = -result.cash_delta
    assert cost >= 0
    closed = result.position
    assert closed.status == OptionStatus.CLOSED
    assert closed.proceeds == -cost
    assert closed.realized_pnl == premium - cost
    assert ensure_default_portfolio(session, user_id).cash_balance == cash_after_write - cost
    assert available_shares(session, portfolio_id, "AAPL") == D(100)


def test_buying_back_a_put_can_spend_its_own_collateral(session: Session) -> None:
    user_id, _ = _account(session)
    position = _write(session, user_id, OptionType.PUT, "100").position
    # Spend everything not held back: only the put's 10,000 is left.
    portfolio = ensure_default_portfolio(session, user_id)
    portfolio.cash_balance = D(10_000)
    session.add(portfolio)
    session.commit()
    assert available_cash(session, portfolio) == D(0)
    result = close_option(session, user_id=user_id, option_id=position.id)  # type: ignore[arg-type]
    assert result.position.status == OptionStatus.CLOSED
    assert available_cash(session, ensure_default_portfolio(session, user_id)) > D(9_000)


# ---------------------------------------------------------------------------
# Expiry: assigned against the cover, or expired with the premium kept
# ---------------------------------------------------------------------------


def _expiring(session: Session, close: float, **position) -> tuple[int, OptionsPosition]:
    _seed_bars(session, [close], end=EXPIRY_SESSION)
    user_id = _make_user(session)
    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.id is not None
    leg = OptionsPosition(
        user_id=user_id, portfolio_id=portfolio.id, ticker="AAPL", quantity=1,
        expiry=TODAY - timedelta(days=1), premium_paid=D(300), side=OptionSide.SHORT,
        **position,
    )  # fmt: skip
    session.add(leg)
    session.commit()
    session.refresh(leg)
    return portfolio.id, leg


def test_an_itm_covered_call_is_assigned_from_the_reserved_shares(session: Session) -> None:
    portfolio_id, leg = _expiring(
        session, 120.0, option_type=OptionType.CALL, strike=D(110), cover=OptionCover.SHARES
    )
    _hold(session, portfolio_id, 100, avg_cost="90")
    assert settle_expired_options(session, settle_date=TODAY) == 1
    session.refresh(leg)
    assert leg.status == OptionStatus.EXERCISED
    assert (leg.proceeds, leg.realized_pnl) == (D(0), D(300))
    (trade,) = session.exec(select(Trade).where(Trade.portfolio_id == portfolio_id)).all()
    # The shares go at the strike, not the 120 close: (110 - 90) x 100 realized on them.
    assert (trade.side, trade.quantity, trade.price) == (TradeSide.SELL, D(100), D(110))
    assert trade.realized_pnl == D(2000)
    assert (
        session.exec(select(Position).where(Position.portfolio_id == portfolio_id)).first() is None
    )


def test_an_otm_covered_call_expires_and_releases_the_shares(session: Session) -> None:
    portfolio_id, leg = _expiring(
        session, 105.0, option_type=OptionType.CALL, strike=D(110), cover=OptionCover.SHARES
    )
    _hold(session, portfolio_id, 100)
    settle_expired_options(session, settle_date=TODAY)
    session.refresh(leg)
    assert leg.status == OptionStatus.EXPIRED
    assert leg.realized_pnl == D(300)
    assert available_shares(session, portfolio_id, "AAPL") == D(100)


def test_an_itm_cash_secured_put_buys_the_shares_with_its_collateral(session: Session) -> None:
    portfolio_id, leg = _expiring(
        session, 80.0, option_type=OptionType.PUT, strike=D(95), cover=OptionCover.CASH
    )
    from stockviz.models import Portfolio

    portfolio = session.get(Portfolio, portfolio_id)
    assert portfolio is not None
    # Spend everything but the collateral, so only the reserved cash can pay.
    portfolio.cash_balance = D(95 * 100)
    session.add(portfolio)
    session.commit()
    settle_expired_options(session, settle_date=TODAY)
    session.refresh(leg)
    assert leg.status == OptionStatus.EXERCISED
    assert leg.realized_pnl == D(300)
    held = session.exec(select(Position).where(Position.portfolio_id == portfolio_id)).one()
    assert (held.quantity, held.avg_cost) == (D(100), D(95))
    session.refresh(portfolio)
    assert portfolio.cash_balance == D(0) - D(300) + D(
        300
    )  # collateral spent, premium kept earlier


def test_short_legs_settle_after_long_ones(session: Session) -> None:
    portfolio_id, short = _expiring(
        session, 120.0, option_type=OptionType.CALL, strike=D(110), cover=OptionCover.SHARES
    )
    long_leg = OptionsPosition(
        user_id=short.user_id, portfolio_id=portfolio_id, ticker="AAPL", quantity=1,
        option_type=OptionType.CALL, strike=D(100), expiry=short.expiry, premium_paid=D(500),
    )  # fmt: skip
    session.add(long_leg)
    session.commit()
    # No shares held: the long call's exercise brings in the 100 the short call delivers.
    assert settle_expired_options(session, settle_date=TODAY) == 2
    trades = session.exec(
        select(Trade).where(Trade.portfolio_id == portfolio_id).order_by(Trade.id)  # type: ignore[arg-type]
    ).all()
    assert [(t.side, t.price) for t in trades] == [
        (TradeSide.BUY, D(100)),
        (TradeSide.SELL, D(110)),
    ]


# ---------------------------------------------------------------------------
# Valuation and the API
# ---------------------------------------------------------------------------


def test_a_short_leg_is_a_liability_in_the_portfolio(session: Session, client: TestClient) -> None:
    user_id, _ = _account(session, shares=100)
    before = client.get("/v1/portfolio", headers=_auth_headers(user_id)).json()
    _write(session, user_id, OptionType.CALL, "110")
    body = client.get("/v1/portfolio", headers=_auth_headers(user_id)).json()
    (leg,) = body["option_positions"]
    assert leg["side"] == "short"
    assert D(leg["market_value"]) < 0
    assert leg["greeks"]["delta"] < 0  # the position loses as the stock rises
    # Written at the model price, so the account is worth the same (to the cent).
    assert D(body["total_value"]) == pytest.approx(D(before["total_value"]), abs=D("0.01"))
    assert D(leg["unrealized_pl"]) == D(leg["market_value"]) + D(leg["premium_paid"])


def test_quote_and_open_short_through_the_api(session: Session, client: TestClient) -> None:
    user_id, _ = _account(session, shares=100)
    params = {
        "ticker": "AAPL", "option_type": "call", "strike": "110",
        "expiry": EXPIRY.isoformat(), "side": "short",
    }  # fmt: skip
    quote = client.get("/v1/options/quote", params=params).json()
    assert quote["side"] == "short"
    assert D(quote["risk"]["shares_reserved"]) == D(100)
    assert quote["risk"]["basis"].startswith("covered call")
    r = client.post(
        "/v1/options/trade",
        headers=_auth_headers(user_id),
        json={"action": "open", "side": "short", "ticker": "AAPL", "option_type": "call",
              "strike": "110", "expiry": EXPIRY.isoformat(), "quantity": 1},
    )  # fmt: skip
    assert r.status_code == 201, r.text
    out = r.json()["position"]
    assert (out["side"], out["cover"], D(out["shares_reserved"])) == ("short", "shares", D(100))
    assert D(out["current_value"]) < 0
    again = client.post(
        "/v1/options/trade",
        headers=_auth_headers(user_id),
        json={"action": "open", "side": "short", "ticker": "AAPL", "option_type": "call",
              "strike": "110", "expiry": EXPIRY.isoformat(), "quantity": 1},
    )  # fmt: skip
    assert again.status_code == 422
    assert "Writing an uncovered call is not allowed" in again.json()["detail"]


def test_a_covered_call_lowers_the_risk_of_the_shares(session: Session, client: TestClient) -> None:
    from tests.test_returns import _bar
    from tests.test_risk import _path, _weekdays

    session.add(Symbol(ticker="AAPL", name="Apple"))
    session.commit()
    closes = _path(150, 11, 300)
    for day, close in zip(_weekdays(300), closes, strict=True):
        session.add(_bar("AAPL", day, str(close)))
    user_id = _make_user(session)
    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.id is not None
    _hold(session, portfolio.id, 200, avg_cost="140")

    def worst() -> float:
        body = client.get("/v1/portfolio/risk", headers=_auth_headers(user_id)).json()
        return max(f["cvar"] for f in body["var"] if f["horizon_days"] == 1)

    shares_only = worst()
    today = utcnow().date()
    session.add(
        OptionsPosition(
            user_id=user_id, portfolio_id=portfolio.id, ticker="AAPL", quantity=2,
            option_type=OptionType.CALL, strike=D(str(round(closes[-1]))),
            expiry=date.fromordinal(today.toordinal() + 30), premium_paid=D(800),
            side=OptionSide.SHORT, cover=OptionCover.SHARES,
        )
    )  # fmt: skip
    session.commit()
    assert worst() < shares_only
